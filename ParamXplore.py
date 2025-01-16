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
RESULTS_DIR = "results"

# Logging Configuration
logging.basicConfig(format='%(message)s', level=logging.INFO)
logger = logging.getLogger()

# Helper Functions
def has_extension(url, extensions):
    """Check if the URL has a file extension matching any of the provided extensions."""
    extension = os.path.splitext(urlparse(url).path)[1].lower()
    return extension in extensions


def clean_url(url):
    """Clean the URL by removing redundant port information for HTTP and HTTPS URLs."""
    parsed_url = urlparse(url)
    if (parsed_url.port == 80 and parsed_url.scheme == "http") or (parsed_url.port == 443 and parsed_url.scheme == "https"):
        parsed_url = parsed_url._replace(netloc=parsed_url.netloc.split(":")[0])
    return parsed_url.geturl()


def clean_urls(urls, domain, extensions, placeholder):
    """Clean a list of URLs by validating domain, removing unnecessary query parameters, and filtering by extension."""
    cleaned_urls = set()
    for url in urls:
        cleaned_url = clean_url(url)

        # Skip URLs not belonging to the intended domain or subdomains
        if domain not in urlparse(cleaned_url).netloc:
            logger.debug(f"[DEBUG] Skipping URL (outside domain): {cleaned_url}")
            continue

        # Skip URLs with hardcoded extensions
        if has_extension(cleaned_url, extensions):
            logger.debug(f"[DEBUG] Skipping URL (disallowed extension): {cleaned_url}")
            continue

        # Process query parameters, replacing their values with a placeholder
        parsed_url = urlparse(cleaned_url)
        query_params = parse_qs(parsed_url.query)
        cleaned_params = {key: placeholder for key in query_params}
        cleaned_query = urlencode(cleaned_params, doseq=True)

        # Reconstruct the URL with cleaned query parameters
        final_url = parsed_url._replace(query=cleaned_query).geturl()
        cleaned_urls.add(final_url)
        logger.debug(f"[DEBUG] Cleaned URL: {final_url}")

    return list(cleaned_urls)


async def fetch_url_content(session, url, proxy=None, retries=3):
    """Fetch the URL content using aiohttp with retries."""
    for attempt in range(retries):
        try:
            async with session.get(url, proxy=proxy, timeout=ClientTimeout(total=10)) as response:
                response.raise_for_status()  # Ensure status is 200-299
                return await response.text()
        except ClientError as e:
            logger.debug(f"[DEBUG] Attempt {attempt + 1} failed for URL {url}: {e}")
            if attempt == retries - 1:
                logger.error(f"{Fore.RED}❌ Failed to fetch URL {url} after {retries} attempts.")
                return None


async def fetch_and_clean_urls(session, domain, extensions, placeholder, proxy, stream_output):
    """Fetch and clean URLs related to a specific domain from the Wayback Machine."""
    logger.info(f"{Fore.BLUE}🔍 Fetching URLs for {domain} 🌐")
    wayback_uri = f"https://web.archive.org/cdx/search/cdx?url={domain}/*&output=txt&collapse=urlkey&fl=original&page=/"
    content = await fetch_url_content(session, wayback_uri, proxy)

    if not content:
        logger.warning(f"{Fore.YELLOW}⚠️ No URLs found for {domain} 🚫")
        return

    urls = content.splitlines()
    cleaned_urls = clean_urls(urls, domain, extensions, placeholder)
    logger.info(f"{Fore.GREEN}✅ Found {len(cleaned_urls)} cleaned URLs for {domain} 🎉")

    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)

    result_file = os.path.join(RESULTS_DIR, f"{domain}.txt")
    with open(result_file, "w") as f:
        for url in cleaned_urls:
            if "?" in url:
                f.write(url + "\n")
                if stream_output:
                    print(f"{Fore.CYAN}🔗 {url}")

    logger.info(f"{Fore.MAGENTA}📁 Saved cleaned URLs to {result_file} 📝")


async def process_domains(domains, extensions, placeholder, proxy, user_agent, max_tasks, stream_output):
    """Process a list of domains asynchronously with concurrency control and progress bar."""
    connector = aiohttp.TCPConnector(limit=max_tasks)
    headers = {"User-Agent": user_agent}

    async with ClientSession(connector=connector, headers=headers) as session:
        tasks = [
            fetch_and_clean_urls(session, domain, extensions, placeholder, proxy, stream_output)
            for domain in domains
        ]
        for task in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Processing Domains 🌍"):
            await task


def load_domains(domain_file=None, domain_name=None):
    """Load a list of domains either from a file or a single domain."""
    if domain_file:
        with open(domain_file, "r") as f:
            domains = [line.strip().lower().replace('https://', '').replace('http://', '') for line in f.readlines()]
            return list(set(filter(None, domains)))  # Remove duplicates and empty lines
    elif domain_name:
        return [domain_name.lower().replace('https://', '').replace('http://', '')]
    else:
        raise ValueError("Either domain_file or domain_name must be provided")


def main():
    """Main function to handle command-line arguments and start URL mining process."""
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

                                         🌟 Automated Parameter Finder 🌟                                  
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
    parser.add_argument("--retries", help="Number of retries for failed requests.", type=int, default=3)
    args = parser.parse_args()

    if not args.domain and not args.list:
        parser.error(f"{Fore.RED}❌ Please provide either the -d option or the -l option.")
    if args.domain and args.list:
        parser.error(f"{Fore.RED}❌ Please provide either the -d option or the -l option, not both.")

    domains = load_domains(domain_file=args.list, domain_name=args.domain)

    # Run the process asynchronously
    asyncio.run(process_domains(
        domains, HARDCODED_EXTENSIONS, args.placeholder, args.proxy,
        args.user_agent, args.max_tasks, args.stream
    ))


if __name__ == "__main__":
    main()

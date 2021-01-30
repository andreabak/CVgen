import argparse
import base64
import os
import time
from dataclasses import dataclass
from getpass import getpass
from io import BytesIO
from typing import (
    MutableMapping,
    Any,
    Mapping,
    Iterator,
    Tuple,
    List,
    Sequence,
    Iterable,
    Optional,
)

import requests
from PyPDF3 import PdfFileReader, PdfFileWriter
from PyPDF3.generic import RectangleObject
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.remote.webdriver import BaseWebDriver
from selenium.webdriver.remote.webelement import WebElement


DEFAULT_PREFS: MutableMapping[str, Any] = {
    "browser.aboutConfig.showWarning": False,
    "pdfjs.disabled": True,
}
PRINT_OPTIONS: Mapping[str, Any] = {
    "scale": 1.0,
    # FIXME: background printing seems broken in FF<=85
    "background": True,
    "printBackground": True,
    "page": {
        "width": 21.0,
        "height": 29.7,
    },
    "margin": {
        "top": 0,
        "left": 0,
        "bottom": 0,
        "right": 0,
    },
    "shrinkToFit": False,
    "pageRanges": ["1"],
}


def flat_iter(d: Mapping[str, Any], sep: str = ".") -> Iterator[Tuple[str, Any]]:
    """
    Flatten a dictionary (or mapping), by merging sub-dictionaries by joining
    their keys with their items' keys using the specified separator.
    :param d: the dictionary (or mapping) to flatten
    :param sep: the separator to join keys with, defaults to "."
    :return: an iterator of (key, value) tuples
    """
    for k, v in d.items():
        if isinstance(v, Mapping):
            for subk, subv in flat_iter(v, sep=sep):
                yield sep.join((k, subk)), subv
        else:
            yield k, v


def flattened(d: Mapping[str, Any], **flat_iter_kwargs) -> MutableMapping[str, Any]:
    """
    Create a flattened copy of the given dictionary. Also see `flat_iter`.
    :param d: the dictionary (or mapping) to flatten
    :param flat_iter_kwargs: additional keyword arguments for the `flat_iter` function
    :return: the new flat dictionary
    """
    return dict(flat_iter(d, **flat_iter_kwargs))


def start_webdriver(prefs: Mapping[str, Any], **kwargs) -> webdriver.Firefox:
    """
    Creates a Firefox WebDriver instance
    :param prefs: preferences to apply to the user profile
    :param kwargs: additional keyword arguments for the WebDriver init
    :return: the created webdriver instance
    """
    profile: webdriver.FirefoxProfile = webdriver.FirefoxProfile()
    for pkey, pval in prefs.items():
        profile.set_preference(pkey, pval)
    options: Options = Options()
    options.add_argument("--headless")
    options.add_argument("-width=1920")
    options.add_argument("-height=1080")
    options.profile = profile
    options.set_capability("marionette", True)
    driver: webdriver.Firefox = webdriver.Firefox(options=options, **kwargs)
    # Patch-in new print WebDriver command
    # FIXME: Refactor once selenium>=4.0.0a8 releases, if includes print command
    # noinspection PyProtectedMember
    driver.command_executor._commands["printPage"] = (
        "POST",
        "/session/$sessionId/print",
    )
    return driver


def wait_for_file(basedir: str, timeout: float = 10.0) -> str:
    timed_out: bool
    start_time = time.time()
    while len(os.listdir(basedir)) != 1:
        if (time.time() - start_time) > timeout:
            timed_out = True
            break
        time.sleep(0.1)
    else:
        timed_out = False
        while os.path.getsize(os.path.join(basedir, os.listdir(basedir)[0])) == 0:
            time.sleep(0.1)
    if timed_out:
        raise FileNotFoundError(f'Timed-out waiting for file in "{basedir}"')
    while True:
        filename = os.listdir(basedir)[0]
        try:
            os.rename(filename, filename)
        except OSError:
            time.sleep(0.1)
        else:
            return filename


@dataclass
class SizedBox:
    x: float
    y: float
    width: float
    height: float

    @property
    def x0(self) -> float:
        return self.x

    @property
    def x1(self) -> float:
        return self.x + self.width

    @property
    def y0(self) -> float:
        return self.y

    @property
    def y1(self) -> float:
        return self.y + self.height

    @classmethod
    def from_webelement(cls, el: WebElement) -> "SizedBox":
        return cls(
            x=el.location["x"],
            y=el.location["y"],
            width=el.size["width"],
            height=el.size["height"],
        )


@dataclass
class Link:
    uri: str
    box: SizedBox


def extract_links(driver: BaseWebDriver, size_relative: bool = True) -> List[Link]:
    body: WebElement = driver.find_element(By.TAG_NAME, "BODY")
    body_box: SizedBox = SizedBox.from_webelement(body)
    rel_scale: float = 1.0 / body_box.width
    links: List[Link] = []
    anchor: WebElement
    for anchor in driver.find_elements(By.TAG_NAME, "A"):
        anchor_box: SizedBox = SizedBox.from_webelement(anchor)
        if not anchor.is_displayed():
            continue
        if size_relative:
            anchor_box = SizedBox(
                x=(anchor_box.x - body_box.x) * rel_scale,
                y=(anchor_box.y - body_box.y) * rel_scale,
                width=anchor_box.width * rel_scale,
                height=anchor_box.height * rel_scale,
            )
        links.append(Link(uri=anchor.get_attribute("href"), box=anchor_box))
    return links


def extract_pdf(driver: BaseWebDriver) -> bytes:
    pdf_b64: str = driver.execute("printPage", PRINT_OPTIONS)["value"]
    pdf_data: bytes = base64.b64decode(pdf_b64)
    return pdf_data


def inject_pdf_links(filepath: str, pdf_data: bytes, links: Iterable[Link]) -> None:
    pdf_stream: BytesIO = BytesIO(pdf_data)
    source_pdf: PdfFileReader = PdfFileReader(pdf_stream)
    pdf_writer: PdfFileWriter = PdfFileWriter()
    pdf_writer.appendPagesFromReader(source_pdf)
    pdf_page_trim_box: RectangleObject = source_pdf.getPage(0).trimBox
    pdf_page_box: SizedBox = SizedBox(
        x=pdf_page_trim_box[0],
        y=pdf_page_trim_box[1],
        width=pdf_page_trim_box[2] - pdf_page_trim_box[0],
        height=pdf_page_trim_box[3] - pdf_page_trim_box[1],
    )
    pdf_scale: float = pdf_page_box.width
    link: Link
    for link in links:
        link_box: SizedBox = SizedBox(
            x=pdf_page_box.x + link.box.x * pdf_scale,
            y=pdf_page_box.y + link.box.y * pdf_scale,
            width=link.box.width * pdf_scale,
            height=link.box.height * pdf_scale,
        )
        # pdf coord system is bottom-left, so invert y
        link_box.y = pdf_page_box.y1 - link_box.y - link_box.height
        # noinspection PyTypeChecker
        pdf_writer.addURI(
            pagenum=0,
            uri=link.uri,  # Broken type annotation in PyPDF3
            rect=[link_box.x0, link_box.y0, link_box.x1, link_box.y1],
            border=[0, 0, 0],
        )
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "wb") as out_fp:
        pdf_writer.write(out_fp)


def create_token(
    base_url: str,
    token_name: str,
    expiry: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    base_name: Optional[str] = None,
    output_path: Optional[str] = None,
) -> Tuple[str, str]:
    if base_name is None and output_path is None:
        raise AttributeError('Must specify one of "base_name" or "output_path"')
    if user is None:
        print("create_token requires authentication")
        user = input("username: ")
    if password is None:
        password = getpass("password: ")
    token_url: str = f"{base_url}/create_token/{token_name}"
    params: MutableMapping[str, Any] = dict()
    if expiry:
        params["expiry"] = expiry
    print(f'Creating new token "{token_name}"')
    response: requests.Response = requests.get(
        url=token_url, params=params, auth=(user, password)
    )
    if response.status_code != 200:
        print(
            "ERROR: Failed creating token!\n"
            f"Response code {response.status_code}: {response.text}"
        )
        exit(-1)
    new_token_id: str = response.text.strip()
    print(f'Created new token with id={new_token_id}')
    pdf_url: str = f"{base_url}/cv/{new_token_id}"
    filepath: str = output_path or os.path.join("pdf", token_name, base_name + ".pdf")
    return pdf_url, filepath


def export_pdf(pdf_url: str, filepath: str) -> None:
    prefs: MutableMapping[str, Any] = dict(flattened(DEFAULT_PREFS))
    driver: webdriver.Firefox
    print("Starting headless firefox through geckodriver")
    with start_webdriver(prefs) as driver:
        print(f"Navigating to {pdf_url}")
        driver.get(pdf_url)
        time.sleep(1)  # TODO: Replace with better waits
        print(f"Extracting page links")
        links: Sequence[Link] = extract_links(driver)
        print(f"Printing page as pdf")
        pdf_data: bytes = extract_pdf(driver)
        print(f"Injecting links into pdf and saving")
        inject_pdf_links(filepath, pdf_data, links)


def main():
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Export web page as PDF using Firefox"
    )

    subparsers = parser.add_subparsers(dest="command")

    export_pdf_args = subparsers.add_parser(
        "export-pdf", help="Export url to pdf"
    )
    export_pdf_args.add_argument(
        "url", help="The URL of the page to process"
    )
    export_pdf_args.add_argument(
        "output", help="The output path for the PDF file"
    )

    create_token_args = subparsers.add_parser(
        "create-token", help="Create new token"
    )
    create_token_args.add_argument(
        "base_url", metavar="URL", help="The base url preceding /create_token/"
    )
    create_token_args.add_argument(
        "token_name", metavar="TOKEN_NAME", help="The name for the new token"
    )
    create_token_args.add_argument(
        "-e", "--expiry", help="Expiry for the new token, if different from default"
    )
    create_token_args.add_argument(
        "-u", "--user", help="Username for authentication"
    )
    create_token_args.add_argument(
        "-p", "--password", help="Password for authentication"
    )
    path_group = create_token_args.add_mutually_exclusive_group()
    path_group.add_argument(
        "-b", "--basename", help="The base name for the PDF file"
    )
    path_group.add_argument(
        "-o", "--output", help="The output path for the PDF file"
    )

    args: argparse.Namespace = parser.parse_args()

    pdf_url: str
    filepath: str
    if args.command == "create-token":
        pdf_url, filepath = create_token(
            args.base_url,
            args.token_name,
            expiry=args.expiry,
            user=args.user,
            password=args.password,
            base_name=args.basename or "cv",
            output_path=args.output,
        )
    elif args.command == "export-pdf":
        pdf_url = args.url
        filepath = args.output
    else:
        raise argparse.ArgumentError(None, "No command specified!")

    export_pdf(pdf_url, filepath)


if __name__ == "__main__":
    main()

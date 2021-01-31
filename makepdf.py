"""Utility script to export a CV to pdf"""

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
    # TODO: background printing seems broken in FF<=85
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
        # pylint: disable=isinstance-second-argument-not-valid-type
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
    # pylint: disable=protected-access
    driver.command_executor._commands["printPage"] = (
        "POST",
        "/session/$sessionId/print",
    )
    return driver


@dataclass
class SizedBox:
    """A simple dataclass to represent a bounding box of a web element"""
    x: float
    y: float
    width: float
    height: float

    @property
    def x0(self) -> float:
        """The left side x-coordinate of the box"""
        return self.x

    @property
    def x1(self) -> float:
        """The right side x-coordinate of the box"""
        return self.x + self.width

    @property
    def y0(self) -> float:
        """The top side y-coordinate of the box"""
        return self.y

    @property
    def y1(self) -> float:
        """The bottom side y-coordinate of the box"""
        return self.y + self.height

    @classmethod
    def from_webelement(cls, element: WebElement) -> "SizedBox":
        """Creates a new `SizedBox` instance from a `WebElement`,
        using its location and size as data"""
        return cls(
            x=element.location["x"],
            y=element.location["y"],
            width=element.size["width"],
            height=element.size["height"],
        )


@dataclass
class Link:
    """A dataclass representing a simple link with its display bounding box"""
    uri: str
    box: SizedBox


def extract_links(driver: BaseWebDriver, size_relative: bool = True) -> List[Link]:
    """
    Extract all the links in the current webpage
    :param driver: the `WebDriver` instance
    :param size_relative: if True (default) the coordinates and sizes of the links'
        bounding boxes will be scaled relatively to the width of the "<body>" element
    :return: a list of Link objects
    """
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


def print_webpage_to_pdf(driver: BaseWebDriver) -> bytes:
    """
    Prints the current webpage of the given webdriver to PDF, using the "Print"
    command as specified in the W3C WebDriver spec
    :param driver: the `WebDriver` instance
    :return: the bytes of the printed pdf data
    """
    pdf_b64: str = driver.execute("printPage", PRINT_OPTIONS)["value"]
    pdf_data: bytes = base64.b64decode(pdf_b64)
    return pdf_data


def inject_pdf_links(
    filepath: str, pdf_data: bytes, links: Iterable[Link], size_relative: bool = True
) -> None:
    """
    Injects links into a pdf file data
    :param filepath: the output file path for the pdf
    :param pdf_data: the source pdf data as bytes
    :param links: an iterable of `Link` objects
    :param size_relative: if True (default) the coordinates and sizes of the links'
        bounding boxes must be relative [0~1] to the width of the pdf page,
        otherwise their absolute values are used
    """
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
    pdf_scale: float = pdf_page_box.width if size_relative else 1.0
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
) -> str:
    """
    Creates a new access token for a CV page
    :param base_url: the base url of the server hosting the CV app
    :param token_name: the name of the new token to create
    :param expiry: a string indicating the expiry interval from now,
        if omitted, the default value configured in the server app will be used
    :param user: the username to use for authentication, if omitted, it will be
        prompted for input at runtime
    :param password: the password to use for authentication, if omitted, it will be
        prompted for input at runtime
    :return: the id of the newly-created token
    """
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
        raise SystemExit(-1)
    new_token_id: str = response.text.strip()
    print(f"Created new token with id={new_token_id}")
    return new_token_id


def export_pdf(url: str, filepath: str) -> None:
    """
    Export a page at the specified url to a pdf file, using selenium and firefox
    :param url: the url of the webpage to export
    :param filepath: the destination pdf file path
    """
    prefs: MutableMapping[str, Any] = dict(flattened(DEFAULT_PREFS))
    driver: webdriver.Firefox
    print("Starting headless firefox through geckodriver")
    with start_webdriver(prefs) as driver:
        print(f"Navigating to {url}")
        driver.get(url)
        time.sleep(1)  # TODO: Replace with better waits
        print("Extracting page links")
        links: Sequence[Link] = extract_links(driver)
        print("Printing page as pdf")
        pdf_data: bytes = print_webpage_to_pdf(driver)
        print("Injecting links into pdf and saving")
        inject_pdf_links(filepath, pdf_data, links)


def main():
    """Main program entry point"""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Export web page as PDF using Firefox"
    )

    subparsers = parser.add_subparsers(dest="command")

    export_pdf_args = subparsers.add_parser("export-pdf", help="Export url to pdf")
    export_pdf_args.add_argument("url", help="The URL of the page to process")
    export_pdf_args.add_argument("output", help="The output path for the PDF file")

    create_token_args = subparsers.add_parser("create-token", help="Create new token")
    create_token_args.add_argument(
        "base_url", metavar="URL", help="The base url preceding /create_token/"
    )
    create_token_args.add_argument(
        "token_name", metavar="TOKEN_NAME", help="The name for the new token"
    )
    create_token_args.add_argument(
        "-e", "--expiry", help="Expiry for the new token, if different from default"
    )
    create_token_args.add_argument("-u", "--user", help="Username for authentication")
    create_token_args.add_argument(
        "-p", "--password", help="Password for authentication"
    )
    path_group = create_token_args.add_mutually_exclusive_group()
    path_group.add_argument("-b", "--basename", help="The base name for the PDF file")
    path_group.add_argument("-o", "--output", help="The output path for the PDF file")

    args: argparse.Namespace = parser.parse_args()

    url: str
    filepath: str
    if args.command == "create-token":
        new_token_id: str = create_token(
            args.base_url,
            args.token_name,
            expiry=args.expiry,
            user=args.user,
            password=args.password,
        )
        url = f"{args.base_url}/cv/{new_token_id}"
        filepath = args.output or os.path.join(
            "pdf", args.token_name, (args.basename or "cv") + ".pdf"
        )
    elif args.command == "export-pdf":
        url = args.url
        filepath = args.output
    else:
        raise argparse.ArgumentError(None, "No command specified!")

    export_pdf(url, filepath)


if __name__ == "__main__":
    main()

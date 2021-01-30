import argparse
import base64
import os
import time
from dataclasses import dataclass
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
)

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
    "background": True,  # FIXME: Seems broken in FF<=85
    "printBackground": True,  # FIXME: Seems broken in FF<=85
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


def inject_pdf_links(filename: str, pdf_data: bytes, links: Iterable[Link]) -> None:
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
            uri=link.uri,
            rect=[link_box.x0, link_box.y0, link_box.x1, link_box.y1],
            border=[0, 0, 0],
        )
    with open(filename, "wb") as out_fp:
        pdf_writer.write(out_fp)


def main():
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Export web page as PDF using Firefox"
    )
    parser.add_argument("url", help="The URL of the page to process")
    parser.add_argument("output", help="The output filepath for the PDF file")

    args: argparse.Namespace = parser.parse_args()

    url: str = args.url
    filename: str = os.path.abspath(args.output)
    tempdir: str
    prefs: MutableMapping[str, Any] = dict(flattened(DEFAULT_PREFS))
    driver: webdriver.Firefox
    with start_webdriver(prefs) as driver:
        driver.get(url)
        # time.sleep(3)  # TODO: Replace with actual waits
        links: Sequence[Link] = extract_links(driver)
        pdf_data: bytes = extract_pdf(driver)
        inject_pdf_links(filename, pdf_data, links)


if __name__ == "__main__":
    main()

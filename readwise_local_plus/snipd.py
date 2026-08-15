"""
Import episode metadata from snipd webpages and store in sqlite.

Extracted data is processed/formatted for db storage only.

Output formatting happens on export.

"""
from pathlib import Path

from bs4 import BeautifulSoup


def fetch_chapters(page_soup: BeautifulSoup) -> str:
    """
    Extract chapter titles and combine into a string.
    
    Returns
    -------
    str:
        Numbered chapter titles split by newlines E.g. "1 - <title>\n"
    """
    chapter_titles_raw = page_soup.find_all(
        "div", class_="episode-details-chapter-title"
    ) 
    chapter_titles = enumerate([title.text for title in chapter_titles_raw])
    
    chapters = ""
    for idx, title in chapter_titles:
        chapters += f"{idx} - {title.strip()}\n"

    return chapters 


def fetch_show_notes(page_soup: BeautifulSoup) -> str:
    """
    Extract show notes and return as a string.

    Returns
    -------
    str
        The show notes in a string. Sentences should end with punctuation
        followed by a space e.g. ". ", "! " etc.

    """
    show_notes_raw = page_soup.find(
        "div", class_="episode-details-description html description"
        )

    show_notes_strings = [s for s in show_notes_raw.strings]

    show_notes_text = ""
    for s in show_notes_strings:
        show_notes_text += (s + " ")

    breakpoint()
    return show_notes_text
    

def run_snipd_metadata_pipeline(podcast_title: str, snipd_url: str):
    # page = requests.get(snipd_url)
    # content = page.content
    # stored_html.write_bytes(content)
    
    stored_html = Path("snipd_example.html")
    content = stored_html.read_text()
    page_soup = BeautifulSoup(content, 'html.parser')

    show_notes = fetch_show_notes(page_soup)
    chapters = fetch_chapters(page_soup)

    # write to db


    

if __name__ == "__main__":
    # url = "https://share.snipd.com/episode/79c2f1c0-8951-4340-8d57-df158cde7ed5" 
    run_snipd_metadata_pipeline("How To Win an Election", "dummy_url")

    # Use this when pulling out of db, add in db more raw
    # nltk.download("punkt_tab")
    # sentences = sent_tokenize(show_notes_text)
    # return sentences
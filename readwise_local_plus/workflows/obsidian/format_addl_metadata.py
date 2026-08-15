import asyncio
import html
import re
from pathlib import Path

from playwright.async_api import async_playwright

HEADINGS = [
    "0 - Intro",
    "1 - Makerfield by-election frames next prime minister",
    "2 - Reform's candidate strengths and weaknesses",
    "3 - What an Andy Burnham win would trigger",
    "4 - Could Burnham control the timetable?",
    "5 - How fast a leadership contest could unfold",
    "6 - The Manchester mayoral complication",
    "7 - Policy signals: WASPI and fiscal trade-offs",
    "8 - Building a Downing Street team quickly",
    "9 - Need for political leadership not just executives",
    "10 - Implications for Reform UK after a loss",
    "11 - Restore versus Reform: competing populisms",
    "12 - Will Belfast incidents revive immigration politics?",
    "13 - Steve Hilton's rise in California politics",
    "14 - Creative imagination in political advisers",
    "15 - Outro",
]

OUTPUT_FILE = Path("chapter_headings_all_dark.png")


def split_heading(heading: str):
    m = re.match(r"^\s*(\d+)\s*-\s*(.+?)\s*$", heading)
    if m:
        return m.group(1), m.group(2)
    return "", heading.strip()


def build_rows(headings):
    rows = []
    for heading in headings:
        number, title = split_heading(heading)
        rows.append(f"""
        <div class="row">
          <div class="badge">{html.escape(number)}</div>
          <div class="text">{html.escape(title)}</div>
        </div>
        """)
    return "\n".join(rows)


def build_html(headings):
    rows_html = build_rows(headings)
    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Chapter Headings</title>
  <style>
    * {{
      box-sizing: border-box;
    }}

    html, body {{
      margin: 0;
      padding: 0;
      background:
        radial-gradient(circle at top left, #1e293b 0%, transparent 30%),
        radial-gradient(circle at bottom right, #0f766e 0%, transparent 24%),
        linear-gradient(180deg, #020617 0%, #0f172a 100%);
      font-family: Inter, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: #e5e7eb;
    }}

    body {{
      padding: 36px;
    }}

    #sheet {{
      width: 1400px;
      margin: 0 auto;
      background:
        radial-gradient(circle at top right, rgba(96,165,250,0.10), transparent 22%),
        linear-gradient(180deg, rgba(15,23,42,0.96) 0%, rgba(2,6,23,0.98) 100%);
      border-radius: 30px;
      padding: 38px;
      border: 1px solid rgba(148,163,184,0.18);
      box-shadow:
        0 30px 90px rgba(0,0,0,0.55),
        inset 0 1px 0 rgba(255,255,255,0.05);
    }}

    .header {{
      margin-bottom: 28px;
      color: #f8fafc;
    }}

    .kicker {{
      font-size: 16px;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #93c5fd;
      margin-bottom: 10px;
    }}

    .title {{
      font-size: 50px;
      line-height: 1.05;
      font-weight: 900;
      letter-spacing: -0.03em;
      margin: 0 0 10px 0;
      color: #ffffff;
      text-shadow: 0 2px 18px rgba(0,0,0,0.35);
    }}

    .subtitle {{
      font-size: 21px;
      line-height: 1.4;
      color: #cbd5e1;
      max-width: 1000px;
      margin: 0;
    }}

    .list {{
      display: flex;
      flex-direction: column;
      gap: 14px;
      margin-top: 24px;
    }}

    .row {{
      display: flex;
      align-items: flex-start;
      gap: 18px;
      padding: 18px 20px;
      border-radius: 20px;
      background: linear-gradient(180deg, rgba(30,41,59,0.92) 0%, rgba(15,23,42,0.92) 100%);
      border: 1px solid rgba(148,163,184,0.16);
      box-shadow:
        0 10px 28px rgba(0,0,0,0.22),
        inset 0 1px 0 rgba(255,255,255,0.04);
    }}

    .badge {{
      flex: 0 0 auto;
      min-width: 58px;
      height: 58px;
      border-radius: 16px;
      background: linear-gradient(180deg, #3b82f6 0%, #2563eb 100%);
      color: white;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 24px;
      font-weight: 900;
      letter-spacing: -0.02em;
      box-shadow:
        0 10px 24px rgba(37,99,235,0.35),
        inset 0 1px 0 rgba(255,255,255,0.16);
    }}

    .text {{
      flex: 1;
      min-width: 0;
      font-size: 30px;
      line-height: 1.25;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: #f8fafc;
      padding-top: 5px;
      word-break: break-word;
    }}
  </style>
</head>
<body>
  <div id="sheet">
    <div class="header">
      <div class="kicker">Contents</div>
      <h1 class="title">Chapter Headings</h1>
      <p class="subtitle">A styled single-image contents page containing all chapter titles.</p>
    </div>

    <div class="list">
      {rows_html}
    </div>
  </div>
</body>
</html>
"""


async def main():
    html_content = build_html(HEADINGS)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1600, "height": 4000}, device_scale_factor=2)

        await page.set_content(html_content)
        await page.locator("#sheet").screenshot(path=str(OUTPUT_FILE))
        await browser.close()

    print(f"Saved {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
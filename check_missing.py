import os
import glob
import re

scientists_dir = "assets/scientists"
events_dir = "assets/events"
names_file = "todayinsci_names.txt"


def normalize(text):
    if not text:
        return ""
    # Lowercase, remove accents/diacritics if simple, remove punctuation/spaces
    text = text.lower()
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


def load_existing():
    existing_scientists = set()
    existing_events = set()

    # Load scientists
    sci_files = glob.glob(os.path.join(scientists_dir, "*.md"))
    for fpath in sci_files:
        filename = os.path.basename(fpath)
        # add slugified filename (without extension)
        slug = os.path.splitext(filename)[0]
        existing_scientists.add(normalize(slug))

        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        parts = content.split("---")
        if len(parts) >= 3:
            frontmatter = parts[1]
            name_m = re.search(r'name:\s*"([^"]*)"', frontmatter)
            surname_m = re.search(r'surname:\s*"([^"]*)"', frontmatter)
            if name_m and surname_m:
                full_name = f"{name_m.group(1)} {surname_m.group(1)}"
                existing_scientists.add(normalize(full_name))
            elif name_m:
                existing_scientists.add(normalize(name_m.group(1)))
            elif surname_m:
                existing_scientists.add(normalize(surname_m.group(1)))

    # Load events
    event_files = glob.glob(os.path.join(events_dir, "*.md"))
    for fpath in event_files:
        filename = os.path.basename(fpath)
        slug = os.path.splitext(filename)[0]
        # remove date prefix if any (e.g., YYYY-MM-DD-)
        slug_no_date = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", slug)
        existing_events.add(normalize(slug_no_date))
        existing_events.add(normalize(slug))

        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        parts = content.split("---")
        if len(parts) >= 3:
            frontmatter = parts[1]
            title_m = re.search(r'title:\s*"([^"]*)"', frontmatter)
            if not title_m:
                title_m = re.search(r"title:\s*([^\n]*)", frontmatter)
            if title_m:
                existing_events.add(normalize(title_m.group(1)))

    return existing_scientists, existing_events


def main():
    if not os.path.exists(names_file):
        print(f"Error: {names_file} not found.")
        return

    existing_scientists, existing_events = load_existing()
    print(f"Loaded {len(existing_scientists)} existing scientist variations.")
    print(f"Loaded {len(existing_events)} existing event variations.")

    missing_names = []
    total_lines = 0

    with open(names_file, "r", encoding="utf-8") as f:
        for line in f:
            total_lines += 1
            line = line.strip()
            if not line:
                continue

            norm_line = normalize(line)
            # check if exists as scientist or event
            if norm_line in existing_scientists or norm_line in existing_events:
                continue

            missing_names.append(line)

    print(f"Total lines in {names_file}: {total_lines}")
    print(f"Missing (unmapped) lines: {len(missing_names)}")

    # Let's print the first 200 missing names
    print("\nFirst 200 missing names:")
    for m in missing_names[:200]:
        print(f"- {m}")


if __name__ == "__main__":
    main()

import os
import glob
import re
import json
import time
import argparse
from google import genai
from google.genai import types

# Directories
scientists_dir = "assets/scientists"
events_dir = "assets/events"
names_file = "todayinsci_names.txt"

os.makedirs(scientists_dir, exist_ok=True)
os.makedirs(events_dir, exist_ok=True)

# Set up Gemini client
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    # Try loading from standard configuration paths of Gemini CLI
    try:
        for path in ["~/.gemini/.env", "~/.env"]:
            expanded_path = os.path.expanduser(path)
            if os.path.exists(expanded_path):
                with open(expanded_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if "GEMINI_API_KEY" in line:
                            m = re.search(
                                r'GEMINI_API_KEY\s*=\s*["\']?([^"\']+)["\']?', line
                            )
                            if m:
                                api_key = m.group(1).strip()
                                break
            if api_key:
                break
    except Exception as e:
        pass

if not api_key:
    print("Warning: GEMINI_API_KEY environment variable not set.")
client = genai.Client(api_key=api_key)


def normalize(text):
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


def slugify(text):
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")


def load_existing():
    existing_scientists = set()
    existing_events = set()

    # Load scientists
    sci_files = glob.glob(os.path.join(scientists_dir, "*.md"))
    for fpath in sci_files:
        filename = os.path.basename(fpath)
        slug = os.path.splitext(filename)[0]
        existing_scientists.add(normalize(slug))

        try:
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
        except Exception as e:
            print(f"Error reading existing scientist file {fpath}: {e}")

    # Load events
    event_files = glob.glob(os.path.join(events_dir, "*.md"))
    for fpath in event_files:
        filename = os.path.basename(fpath)
        slug = os.path.splitext(filename)[0]
        slug_no_date = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", slug)
        existing_events.add(normalize(slug_no_date))
        existing_events.add(normalize(slug))

        try:
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
        except Exception as e:
            print(f"Error reading existing event file {fpath}: {e}")

    return existing_scientists, existing_events


def build_prompt(chunk):
    lines_str = "\n".join([f"- {item}" for item in chunk])

    prompt = f"""You are an expert scientific historian and copywriter.
For each of the following lines from a science history database, determine if it refers to a famous Scientific Personality (scientist, inventor, discoverer) or to a Scientific Event/Discovery.

Lines to analyze:
{lines_str}

Please classify each line and retrieve the factual historical metadata and content.
Return a single JSON object containing a "results" array.
Each element in "results" must contain:
1. "original_line": exact line from the list.
2. "classification": either "scientist", "event", or "unknown".
3. "scientist_data": (REQUIRED if classification is "scientist")
   - "name": first names (e.g. "Albert" or "Aage N.")
   - "surname": last name (e.g. "Einstein" or "Bohr")
   - "gender": "Male", "Female", "Other", or ""
   - "nationality": array of strings (e.g. ["German", "American"])
   - "birth_date": "YYYY-MM-DD" (exact birth date. If year is known but not month/day, use "YYYY-01-01". If entirely unknown, use "unknown")
   - "death_date": "YYYY-MM-DD" (exact death date. If still alive, use "". If unknown, use "unknown")
   - "disciplines": array of strings representing scientific fields (e.g. ["Physics", "Cosmology"])
   - "headline": a brief, punchy one-sentence summary of what they are famous for.
   - "quote": a famous quote of theirs, or empty string "" if none.
   - "summary": a short, witty, and engaging biography of the scientist. Write like a real, slightly cheeky human for social media. Avoid AI clichés like 'delve', 'tapestry', 'testament', or 'landscape'. 500 to 1500 characters.
4. "event_data": (REQUIRED if classification is "event")
   - "title": a clean, engaging title for the event (e.g. "First public demonstration of 3-D TV")
   - "date": "YYYY-MM-DD" of the exact historical date of this event. If exact day is unknown, use "YYYY-MM-01" or "YYYY-01-01".
   - "event_type": the type of event (e.g. "Invention", "Scientific Publication", "Discovery", "Patent", "First Flight", etc.)
   - "disciplines": array of strings representing scientific fields (e.g. ["Engineering", "Optics"])
   - "associated_people": array of names of key figures associated with this event (e.g. ["John Logie Baird"])
   - "headline": a punchy, hook-like one-sentence summary of the event.
   - "summary": an engaging, lively description of the event, explaining why it was a big deal, and how it happened. Write in a witty, slightly cheekily conversational tone. Avoid AI clichés. 500 to 1500 characters.

Ensure ALL birth dates, death dates, and event dates are as historically accurate as possible.
Return strictly valid JSON according to this structure. No Markdown around the JSON.
"""
    return prompt


def create_scientist_card(data):
    name = data.get("name", "").strip()
    surname = data.get("surname", "").strip()
    if not name and not surname:
        return None, "Error: Name and surname are both empty."

    slug = f"{slugify(name)}-{slugify(surname)}".strip("-")
    fpath = os.path.join(scientists_dir, f"{slug}.md")

    if os.path.exists(fpath):
        return slug, f"Skipped: scientist card '{slug}.md' already exists."

    # Build frontmatter
    frontmatter = []
    frontmatter.append("---")
    frontmatter.append(f'name: "{name}"')
    frontmatter.append(f'surname: "{surname}"')

    gender = data.get("gender", "")
    frontmatter.append(f'gender: "{gender}"')

    frontmatter.append("nationality:")
    for nat in data.get("nationality", []):
        frontmatter.append(f'  - "{nat}"')

    birth_date = data.get("birth_date", "unknown")
    frontmatter.append(f'birth_date: "{birth_date}"')

    death_date = data.get("death_date", "")
    frontmatter.append(f'death_date: "{death_date}"')

    frontmatter.append("disciplines:")
    for disc in data.get("disciplines", []):
        frontmatter.append(f'  - "{disc}"')

    headline = data.get("headline", "").replace('"', '\\"')
    frontmatter.append(f'headline: "{headline}"')

    quote = data.get("quote", "").replace('"', '\\"')
    frontmatter.append(f'quote: "{quote}"')

    frontmatter.append(f'image: "{slug}.png"')
    frontmatter.append("---")

    yaml_str = "\n".join(frontmatter)
    content = f"{yaml_str}\n\n{data.get('summary', '')}\n"

    with open(fpath, "w", encoding="utf-8") as f:
        f.write(content)
        print(f"Created scientist card: {slug}.md")

    return slug, f"Created scientist card: {slug}.md"


def create_event_card(data):
    title = data.get("title", "").strip()
    if not title:
        return None, "Error: Event title is empty."

    date_str = data.get("date", "unknown")
    if not date_str or date_str == "unknown":
        date_str = "0000-00-00"

    slug = slugify(title)
    filename = f"{date_str}-{slug}.md"
    fpath = os.path.join(events_dir, filename)

    if os.path.exists(fpath):
        return slug, f"Skipped: event card '{filename}' already exists."

    # Build frontmatter
    frontmatter = []
    frontmatter.append("---")
    title_escaped = title.replace('"', '\\"')
    frontmatter.append(f'title: "{title_escaped}"')
    frontmatter.append(f"date: {date_str}")

    event_type_escaped = data.get("event_type", "Discovery").replace('"', '\\"')
    frontmatter.append(f'event_type: "{event_type_escaped}"')

    disciplines_quoted = [
        f'"{d.strip().replace('"', '\\"')}"' for d in data.get("disciplines", [])
    ]
    disciplines_str = ", ".join(disciplines_quoted)
    frontmatter.append(f"disciplines: [{disciplines_str}]")

    associated_escaped = ", ".join(data.get("associated_people", [])).replace(
        '"', '\\"'
    )
    frontmatter.append(f'associated_people: "{associated_escaped}"')

    headline = data.get("headline", "").replace('"', '\\"')
    frontmatter.append(f'headline: "{headline}"')
    frontmatter.append(f"image: {slug}.png")
    frontmatter.append("---")

    yaml_str = "\n".join(frontmatter)
    content = f"{yaml_str}\n\n{data.get('summary', '')}\n"

    with open(fpath, "w", encoding="utf-8") as f:
        f.write(content)
        print(f"Created event card: {filename}")
    return filename, f"Created event card: {filename}"


def process_batch(chunk):
    prompt = build_prompt(chunk)
    print(f"Sending prompt to Gemini for batch of {len(chunk)} items...")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )

        data = json.loads(response.text)
        results = data.get("results", [])

        for result in results:
            orig = result.get("original_line", "")
            classification = result.get("classification", "unknown")

            if classification == "scientist":
                sci_data = result.get("scientist_data")
                if sci_data:
                    _, msg = create_scientist_card(sci_data)
                    print(f"[{orig}] -> {msg}")
                else:
                    print(
                        f"[{orig}] -> Error: classified as scientist but missing scientist_data"
                    )
            elif classification == "event":
                evt_data = result.get("event_data")
                if evt_data:
                    _, msg = create_event_card(evt_data)
                    print(f"[{orig}] -> {msg}")
                else:
                    print(
                        f"[{orig}] -> Error: classified as event but missing event_data"
                    )
            else:
                print(f"[{orig}] -> Classified as unknown or skipped.")

    except Exception as e:
        print(f"Error processing batch {chunk}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Process todayinsci_names.txt and generate cards."
    )
    parser.add_argument(
        "--limit-batches",
        type=int,
        default=10,
        help="Number of batches of 15 to process (default: 2)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all missing names (warning: can be slow/costly)",
    )
    args = parser.parse_args()

    if not os.path.exists(names_file):
        print(f"Error: {names_file} not found.")
        return

    print("Loading existing cards...")
    existing_scientists, existing_events = load_existing()
    print(
        f"Loaded {len(existing_scientists)} existing scientists and {len(existing_events)} existing events (including aliases)."
    )

    missing_names = []
    with open(names_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            norm = normalize(line)
            if norm in existing_scientists or norm in existing_events:
                continue
            missing_names.append(line)

    print(f"Total missing lines to process: {len(missing_names)}")
    if not missing_names:
        print("All names have already been processed!")
        return

    batch_size = 15
    if args.all:
        total_batches = (len(missing_names) + batch_size - 1) // batch_size
        print(f"Processing ALL {total_batches} batches...")
    else:
        total_batches = args.limit_batches
        print(
            f"Processing limited to {total_batches} batch(es) of size {batch_size}..."
        )

    for i in range(total_batches):
        start_idx = i * batch_size
        if start_idx >= len(missing_names):
            break
        chunk = missing_names[start_idx : start_idx + batch_size]
        print(
            f"\n--- Batch {i + 1}/{total_batches} (Processing {len(chunk)} items) ---"
        )
        print(f"Items: {chunk}")

        process_batch(chunk)

        # Rate limit safety delay
        time.sleep(2)

    print("\nFinished processing batch.")


if __name__ == "__main__":
    main()

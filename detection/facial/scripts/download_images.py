"""
Download ~50 diverse face images and ~50 no-face images for benchmarking.

Face images: Wikipedia REST API thumbnails for well-known public figures,
chosen to span different genders, ethnicities, ages, and skin tones.

No-face images: COCO 2017 val subset filtered to images with zero 'person'
annotations (landscapes, vehicles, food, interiors, animals).

Usage:
    python scripts/download_images.py
"""

import json
import time
import random
import urllib.request
import urllib.error
from pathlib import Path

FACES_DIR = Path(__file__).parent.parent / "images" / "faces"
NO_FACES_DIR = Path(__file__).parent.parent / "images" / "no_faces"
TARGET_FACES = 90
TARGET_NO_FACES = 95

WIKI_API = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

# Diverse public figures: politicians, athletes, entertainers, scientists
# spanning Black, White, Asian, Latino, Middle Eastern, men, women, various ages
WIKI_PEOPLE = [
    # Black men
    "Barack_Obama", "Nelson_Mandela", "Kofi_Annan", "Morgan_Freeman",
    "Denzel_Washington", "LeBron_James", "Usain_Bolt", "Tiger_Woods",
    "Colin_Powell", "Mike_Tyson", "Will_Smith", "Samuel_L._Jackson",
    "Idris_Elba", "Dwayne_Johnson", "Kevin_Hart", "Kanye_West",
    "Jay-Z", "50_Cent", "Chiwetel_Ejiofor", "Trevor_Noah",
    "Kobe_Bryant", "Michael_Jordan", "Muhammad_Ali", "Nelson_Piquet_Jr.",
    # Black women
    "Serena_Williams", "Oprah_Winfrey", "Condoleezza_Rice",
    "Naomi_Campbell", "Lupita_Nyong%27o", "Michelle_Obama",
    "Viola_Davis", "Kerry_Washington", "Whoopi_Goldberg",
    "Beyonc%C3%A9", "Rihanna", "Misty_Copeland",
    # White men
    "Vladimir_Putin", "Emmanuel_Macron", "Boris_Johnson", "Bill_Clinton",
    "Arnold_Schwarzenegger", "Roger_Federer", "David_Beckham",
    "Paul_McCartney", "Elon_Musk", "Bill_Gates",
    "Tom_Hanks", "Brad_Pitt", "Johnny_Depp", "Leonardo_DiCaprio",
    "Robert_De_Niro", "Anthony_Hopkins", "Ringo_Starr", "Mick_Jagger",
    "Stephen_Hawking", "Neil_deGrasse_Tyson", "Richard_Branson",
    "Gerhard_Schr%C3%B6der", "Silvio_Berlusconi", "Tony_Blair",
    # White women
    "Angela_Merkel", "Hillary_Clinton", "Angelina_Jolie",
    "Scarlett_Johansson", "Cate_Blanchett", "Meryl_Streep",
    "Emma_Watson", "Nicole_Kidman", "Kate_Blanchett",
    "Madonna_(entertainer)", "Taylor_Swift", "Adele",
    "Margaret_Thatcher", "Theresa_May", "Christine_Lagarde",
    # Asian men
    "Junichiro_Koizumi", "Wen_Jiabao", "Lee_Kuan_Yew",
    "Jackie_Chan", "Jet_Li", "Shinzo_Abe",
    "Dalai_Lama", "Xi_Jinping", "Moon_Jae-in",
    "Akira_Kurosawa", "Yao_Ming", "Ang_Lee",
    # Asian women
    "Yoko_Ono", "Ai_Sugiyama", "Michelle_Yeoh",
    "Aung_San_Suu_Kyi", "Malala_Yousafzai",
    "Zhang_Ziyi", "Gong_Li", "Lucy_Liu",
    "Priyanka_Chopra", "Mindy_Kaling",
    # Latino/Hispanic
    "Jennifer_Lopez", "Shakira", "Alejandro_Toledo",
    "Luiz_In%C3%A1cio_Lula_da_Silva", "Vicente_Fox",
    "Salma_Hayek", "Antonio_Banderas", "Enrique_Iglesias",
    "Lionel_Messi", "Pel%C3%A9", "Ronaldinho",
    # Middle Eastern / South Asian
    "Hamid_Karzai", "Mahmoud_Abbas", "Yasser_Arafat",
    "Atal_Bihari_Vajpayee", "Narendra_Modi",
    "Benazir_Bhutto", "Recep_Tayyip_Erdo%C4%9Fan", "Hassan_Rouhani",
    # Indigenous / Pacific
    "Jacinda_Ardern", "Che_Guevara",
    # Elderly faces
    "Jimmy_Carter", "Fidel_Castro", "Jacques_Chirac",
    "Queen_Elizabeth_II", "Pope_Francis", "Desmond_Tutu",
    "Warren_Buffett", "Henry_Kissinger",
    # Younger faces
    "Greta_Thunberg", "Billie_Eilish", "Zendaya",
    "Justin_Bieber", "Millie_Bobby_Brown",
]

# ---------------------------------------------------------------------------
# Wikipedia subjects that are guaranteed face-free: landscapes, food, animals,
# architecture, vehicles, plants, abstract. One thumbnail per article.
# ---------------------------------------------------------------------------
WIKI_NO_FACE_SUBJECTS = [
    # Landscapes / nature
    "Grand_Canyon", "Amazon_rainforest", "Sahara", "Mount_Everest",
    "Niagara_Falls", "Great_Barrier_Reef", "Aurora_borealis", "Atacama_Desert",
    "Mariana_Trench", "Yellowstone_National_Park", "Fiordland_National_Park",
    "Patagonia", "Gobi_Desert", "Serengeti", "Victoria_Falls",
    "Antelope_Canyon", "Dead_Sea", "Ha_Long_Bay", "Loch_Ness",
    "Mount_Fuji", "Iguazu_Falls", "Namib_Desert", "Glacier_National_Park",
    "Plitvice_Lakes_National_Park", "Angel_Falls", "Cliffs_of_Moher",
    # Food & drink
    "Pizza", "Sushi", "Ramen", "Croissant", "Hamburger", "Pad_thai",
    "Chocolate_cake", "Espresso", "Tacos", "Dim_sum", "Baklava",
    "Paella", "Pho", "Naan", "Gelato",
    "Peking_duck", "Cheese", "Baguette", "Mochi", "Falafel",
    "Tiramisu", "Biryani", "Fish_and_chips", "Kimchi", "Empanada",
    # Animals (non-human)
    "Siberian_tiger", "African_elephant", "Giant_panda", "Blue_whale",
    "Golden_eagle", "Komodo_dragon", "Snow_leopard", "Bottlenose_dolphin",
    "Red_fox", "Polar_bear", "Cheetah", "Gorilla", "Peacock",
    "Mandarin_fish", "Axolotl",
    "Octopus", "Hummingbird", "Narwhal", "Fennec_fox", "Chameleon",
    "Manta_ray", "Platypus", "Capybara", "Pangolin", "Quokka",
    # Architecture / objects
    "Colosseum", "Sagrada_Familia", "Parthenon", "Taj_Mahal",
    "Sydney_Opera_House", "Eiffel_Tower", "Burj_Khalifa", "Stonehenge",
    "Great_Wall_of_China", "Machu_Picchu",
    "Angkor_Wat", "Hagia_Sophia", "Neuschwanstein_Castle",
    "Petra", "Alhambra", "Forbidden_City", "Chichen_Itza",
    # Vehicles / tech
    "Formula_One", "Space_Shuttle", "Airbus_A380", "Steam_locomotive",
    "Container_ship", "Bullet_train", "Submarine", "Hot_air_balloon",
    "Concorde", "International_Space_Station",
    # Plants / other
    "Cherry_blossom", "Sunflower", "Bonsai", "Cactus",
    "Mushroom", "Coral_reef",
    "Lavender", "Bamboo", "Redwood", "Orchid",
    "Milky_Way", "Lightning", "Tsunami", "Volcano",
]


def download_file(url: str, dest: Path, label: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FaceDetectionBenchmark/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        if len(data) < 2000:
            print(f"  SKIP (too small): {label}")
            return False
        dest.write_bytes(data)
        return True
    except Exception as e:
        print(f"  FAIL {label}: {e}")
        return False


def get_wiki_thumbnail(title: str) -> str | None:
    url = WIKI_API.format(title=title)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FaceDetectionBenchmark/1.0 (research)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        # Use thumbnail as-is — do NOT modify the URL, Wikimedia enforces strict thumb steps
        return data.get("thumbnail", {}).get("source")
    except Exception as e:
        print(f"  WIKI FAIL {title}: {e}")
        return None


def download_faces():
    FACES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n=== Downloading face images -> {FACES_DIR} ===")

    existing = sorted(FACES_DIR.glob("*.jpg"))
    already = len(existing)
    if existing:
        last = existing[-1].stem
        try:
            start_idx = int(last.split("_")[-1]) + 1
        except ValueError:
            start_idx = already + 1
    else:
        start_idx = 1

    need = TARGET_FACES - already
    if need <= 0:
        print(f"  Already have {already} images, nothing to download.")
        return already

    print(f"  Have {already}, need {need} more (starting at face_{start_idx:03d})")
    downloaded = 0
    idx = start_idx
    people = list(WIKI_PEOPLE)
    random.shuffle(people)

    for person in people:
        if downloaded >= need:
            break
        display = person.replace("_", " ")
        print(f"  [{already + downloaded + 1:02d}/{TARGET_FACES}] {display}...", end=" ", flush=True)
        thumb_url = get_wiki_thumbnail(person)
        if not thumb_url:
            continue
        dest = FACES_DIR / f"face_{idx:03d}.jpg"
        ok = download_file(thumb_url, dest, display)
        if ok:
            print("OK")
            downloaded += 1
            idx += 1
        else:
            print()
        time.sleep(1.0)

    total = already + downloaded
    print(f"\nDownloaded {downloaded} new face images ({total} total).")
    return total


def download_no_faces():
    NO_FACES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n=== Downloading no-face images -> {NO_FACES_DIR} ===")

    existing = sorted(NO_FACES_DIR.glob("*.jpg"))
    already = len(existing)
    # Start idx after highest existing file number
    if existing:
        last = existing[-1].stem  # e.g. "neg_022"
        try:
            start_idx = int(last.split("_")[-1]) + 1
        except ValueError:
            start_idx = already + 1
    else:
        start_idx = 1

    need = TARGET_NO_FACES - already
    if need <= 0:
        print(f"  Already have {already} images, nothing to download.")
        return already

    print(f"  Have {already}, need {need} more (starting at neg_{start_idx:03d})")
    downloaded = 0
    idx = start_idx
    subjects = list(WIKI_NO_FACE_SUBJECTS)
    random.shuffle(subjects)

    for subject in subjects:
        if downloaded >= need:
            break
        display = subject.replace("_", " ")
        print(f"  [{already + downloaded + 1:02d}/{TARGET_NO_FACES}] {display}...", end=" ", flush=True)
        thumb_url = get_wiki_thumbnail(subject)
        if not thumb_url:
            continue
        dest = NO_FACES_DIR / f"neg_{idx:03d}.jpg"
        ok = download_file(thumb_url, dest, display)
        if ok:
            print("OK")
            downloaded += 1
            idx += 1
        else:
            print()
        time.sleep(1.0)

    total = already + downloaded
    print(f"\nDownloaded {downloaded} new no-face images ({total} total).")
    return total


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--faces-only", action="store_true")
    parser.add_argument("--no-faces-only", action="store_true")
    args = parser.parse_args()

    random.seed(42)
    faces = download_faces() if not args.no_faces_only else len(list(FACES_DIR.glob("*.jpg")))
    no_faces = download_no_faces() if not args.faces_only else len(list(NO_FACES_DIR.glob("*.jpg")))
    print(f"\nDone. Faces: {faces}  No-faces: {no_faces}")
    print(f"Face dir:    {FACES_DIR}")
    print(f"No-face dir: {NO_FACES_DIR}")

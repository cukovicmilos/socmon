#!/usr/bin/env python3
"""Instagram notifier - skenira praćene profile za nove postove i šalje Telegram notifikacije."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import instaloader

SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / 'ig_state.db'
PROFILES_PATH = SCRIPT_DIR / 'profiles.txt'
NOTIFY_BIN = '/var/www/html/notifierbot/notify'
MAX_INIT_POSTS = 10
SESSION_USER = 'cukovicmilos'


def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.execute('''CREATE TABLE IF NOT EXISTS seen_posts (
        profile TEXT NOT NULL,
        shortcode TEXT NOT NULL,
        date_utc TEXT NOT NULL,
        first_seen TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        PRIMARY KEY (profile, shortcode)
    )''')
    db.commit()
    return db


def is_first_run(db, profile):
    row = db.execute(
        'SELECT COUNT(*) FROM seen_posts WHERE profile = ?', (profile,)
    ).fetchone()
    return row[0] == 0


def is_seen(db, profile, shortcode):
    row = db.execute(
        'SELECT COUNT(*) FROM seen_posts WHERE profile = ? AND shortcode = ?',
        (profile, shortcode)
    ).fetchone()
    return row[0] > 0


def mark_seen(db, profile, shortcode, date_utc):
    db.execute(
        'INSERT OR IGNORE INTO seen_posts (profile, shortcode, date_utc) VALUES (?, ?, ?)',
        (profile, shortcode, str(date_utc))
    )


def send_notification(profile, shortcode, caption, date_utc):
    post_url = f'https://instagram.com/p/{shortcode}/'
    formatted_date = date_utc.strftime('%d.%m.%Y %H:%M') if date_utc else 'nepoznato'

    message = f'Novi post od @{profile}'

    cmd = [
        NOTIFY_BIN, 'instagram', message,
        f'--link={post_url}',
        f'--date={formatted_date}',
    ]
    if caption:
        cmd.append(f'--caption={caption[:300]}')

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            print(f"Notify failed for @{profile}/{shortcode}: {result.stderr.strip()}",
                  file=sys.stderr)
        else:
            print(f"Notified: @{profile} -> {post_url}")
    except Exception as e:
        print(f"Error sending notification for @{profile}/{shortcode}: {e}", file=sys.stderr)


def scan_profile(L, db, username):
    try:
        profile = instaloader.Profile.from_username(L.context, username)
    except instaloader.ProfileNotExistsException:
        print(f"Profile '{username}' does not exist.", file=sys.stderr)
        return
    except instaloader.exceptions.PrivateProfileNotFollowedException:
        print(f"Profile '{username}' is private and not followed — skipping.", file=sys.stderr)
        return
    except Exception as e:
        print(f"Error fetching profile '{username}': {e}", file=sys.stderr)
        return

    first_run = is_first_run(db, username)

    if first_run:
        print(f"[{username}] Prvo skeniranje — seed-ujem poslednjih {MAX_INIT_POSTS} postova bez notifikacije...")

    new_count = 0
    post_count = 0

    try:
        for post in profile.get_posts():
            post_count += 1

            if first_run and post_count > MAX_INIT_POSTS:
                break

            shortcode = post.shortcode

            if is_seen(db, username, shortcode):
                break

            if not first_run:
                send_notification(
                    profile=username,
                    shortcode=shortcode,
                    caption=post.caption,
                    date_utc=post.date_utc
                )
                new_count += 1

            mark_seen(db, username, shortcode, post.date_utc)

    except instaloader.exceptions.ConnectionException as e:
        print(f"Connection error for '{username}': {e}", file=sys.stderr)
    except Exception as e:
        print(f"Error iterating posts for '{username}': {e}", file=sys.stderr)

    db.commit()

    if first_run:
        print(f"[{username}] Seed-ovano {min(post_count, MAX_INIT_POSTS)} postova.")
    else:
        print(f"[{username}] {new_count} novih postova (skenirano {post_count}).")


def main():
    if not PROFILES_PATH.exists():
        print(f"profiles.txt not found at {PROFILES_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(PROFILES_PATH) as f:
        profiles = [
            line.strip() for line in f
            if line.strip() and not line.startswith('#')
        ]

    if not profiles:
        print("No profiles to track in profiles.txt", file=sys.stderr)
        sys.exit(1)

    L = instaloader.Instaloader(
        user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
    )

    try:
        L.load_session_from_file(SESSION_USER)
        print("Sesija učitana.")
    except FileNotFoundError:
        print(
            f"Session file not found. Pokreni: instaloader --login {SESSION_USER}",
            file=sys.stderr
        )
        sys.exit(2)
    except Exception as e:
        print(f"Sesija nije učitana: {e}", file=sys.stderr)
        sys.exit(2)

    db = get_db()

    for username in profiles:
        try:
            scan_profile(L, db, username)
        except Exception as e:
            print(f"Unhandled error for '{username}': {e}", file=sys.stderr)

    db.close()
    print("Skeniranje završeno.")


if __name__ == '__main__':
    main()

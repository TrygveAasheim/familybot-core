#!/usr/bin/env python3
"""
Kanban board CLI for FamilyBot.
Called by the agent when users add/list/complete tasks via Telegram.

Usage:
  python3 kanban.py add --title "..." --assigned <configured-name>|both --priority must-do|important|nice-to [--due 2026-05-01] [--description "..."]
  python3 kanban.py list [--assigned <configured-name>|both]
  python3 kanban.py done --id 3
  python3 kanban.py done --title "partial match"
"""

import sqlite3
import argparse
import json
import os
import sys
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(__file__))
from reliability import database_path

DB_PATH = str(database_path())


def db():
    return sqlite3.connect(DB_PATH)


def add_card(title, assigned_to, priority="nice-to", due_date=None, description=None):
    conn = db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO kanban_cards (title, description, assigned_to, lane, priority, due_date)
        VALUES (?, ?, ?, 'todo', ?, ?)
    """, (title, description, assigned_to, priority, due_date))
    card_id = c.lastrowid
    conn.commit()
    conn.close()
    return card_id


def list_cards(assigned_to=None):
    conn = db()
    c = conn.cursor()
    if assigned_to and assigned_to != "both":
        rows = c.execute("""
            SELECT id, title, assigned_to, priority, lane, due_date
            FROM kanban_cards
            WHERE lane != 'done' AND archived_at IS NULL
              AND (assigned_to=? OR assigned_to='both')
            ORDER BY CASE priority WHEN 'must-do' THEN 1 WHEN 'important' THEN 2 ELSE 3 END,
                     due_date NULLS LAST
        """, (assigned_to,)).fetchall()
    else:
        rows = c.execute("""
            SELECT id, title, assigned_to, priority, lane, due_date
            FROM kanban_cards
            WHERE lane != 'done' AND archived_at IS NULL
            ORDER BY CASE priority WHEN 'must-do' THEN 1 WHEN 'important' THEN 2 ELSE 3 END,
                     due_date NULLS LAST
        """).fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "assigned_to": r[2],
             "priority": r[3], "lane": r[4], "due": r[5]} for r in rows]


def complete_card(card_id=None, title_match=None):
    conn = db()
    c = conn.cursor()
    if card_id:
        row = c.execute("SELECT id, title FROM kanban_cards WHERE id=?", (card_id,)).fetchone()
    elif title_match:
        row = c.execute("""
            SELECT id, title FROM kanban_cards
            WHERE lower(title) LIKE ? AND lane != 'done' AND archived_at IS NULL
            LIMIT 1
        """, (f"%{title_match.lower()}%",)).fetchone()
    else:
        conn.close()
        return None

    if row:
        c.execute("""
            UPDATE kanban_cards SET lane='done', updated_at=datetime('now')
            WHERE id=?
        """, (row[0],))
        conn.commit()
        conn.close()
        return row[1]
    conn.close()
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")

    # add
    p_add = sub.add_parser("add")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--assigned", default="both")
    p_add.add_argument("--priority", default="nice-to",
                       choices=["must-do", "important", "nice-to"])
    p_add.add_argument("--due")
    p_add.add_argument("--description")

    # list
    p_list = sub.add_parser("list")
    p_list.add_argument("--assigned")

    # done
    p_done = sub.add_parser("done")
    p_done.add_argument("--id", type=int)
    p_done.add_argument("--title")

    args = parser.parse_args()

    if args.cmd == "add":
        card_id = add_card(args.title, args.assigned, args.priority,
                           args.due, args.description)
        print(json.dumps({"ok": True, "id": card_id, "title": args.title,
                          "assigned": args.assigned, "priority": args.priority}))

    elif args.cmd == "list":
        cards = list_cards(args.assigned)
        print(json.dumps({"ok": True, "cards": cards, "count": len(cards)}))

    elif args.cmd == "done":
        title = complete_card(card_id=args.id, title_match=args.title)
        if title:
            print(json.dumps({"ok": True, "completed": title}))
        else:
            print(json.dumps({"ok": False, "error": "Card not found"}))
            sys.exit(1)

    else:
        parser.print_help()

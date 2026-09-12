module ConvertedFiles.SyncNavPy

let file = """#!/usr/bin/env python3
import os
import sys
import tomllib
from pathlib import Path

ZENSICAL_TOML = "zensical.toml"
DOCS_DIR = "docs"

# ------------------------------------------------------------
# Load TOML
# ------------------------------------------------------------
def load_toml_nav():
    with open(ZENSICAL_TOML, "rb") as f:
        data = tomllib.load(f)
    nav = data.get("project", {}).get("nav", [])
    return data, nav

# ------------------------------------------------------------
# Flatten nav into list of referenced files + section paths
# ------------------------------------------------------------
def flatten_nav_with_paths(nav, section_path=None):
    if section_path is None:
        section_path = []
    entries = []
    for item in nav:
        if isinstance(item, str):
            entries.append((section_path[:], item))
        elif isinstance(item, dict):
            for name, v in item.items():
                if isinstance(v, str):
                    entries.append((section_path + [name], v))
                elif isinstance(v, list):
                    entries.extend(flatten_nav_with_paths(v, section_path + [name]))
    return entries

def flatten_nav(nav):
    return [fp for _, fp in flatten_nav_with_paths(nav)]

# ------------------------------------------------------------
# Scan docs directory
# ------------------------------------------------------------
def scan_docs():
    md_files = []
    for root, _, files in os.walk(DOCS_DIR):
        for f in files:
            if f.lower().endswith(".md"):
                full = Path(root) / f
                rel = full.relative_to(DOCS_DIR).as_posix()
                md_files.append(rel)
    return sorted(md_files)

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def auto_title(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").title()

def user_input(prompt):
    val = input(prompt).strip()
    if val.lower() == "quit":
        print("\nQuit command received. Saving current nav state and exiting.")
        # Write nav to nav.txt before exiting
        # (Assumes `data` and `nav` are in scope or passed in)
        raise SystemExit("quit")
    return val

def infer_page_name(file_path: str) -> str:
    name = Path(file_path).name
    stem = Path(file_path).stem
    if name.lower() == "readme.md":
        inferred = "About"
    else:
        inferred = auto_title(stem)
    yn = user_input(f"Infer page name '{inferred}'? (Y/n): ").strip().lower()
    if yn in ("", "y"):
        return inferred
    return user_input("Enter custom page name: ").strip()

def find_section(nav, name):
    for item in nav:
        if isinstance(item, dict) and name in item:
            value = item[name]

            # Case A: section (list)
            if isinstance(value, list):
                return value

            # Case B: page (string)
            if isinstance(value, str):
                return "PAGE"

    # Case C: missing section
    return None



def ensure_subsection(section_list, subsection_name):
    # Look for an existing subsection with this name
    for item in section_list:
        if isinstance(item, dict) and subsection_name in item:
            subsection = item[subsection_name]
            # Guarantee it's a list (TOML nav requires list for subsections)
            if not isinstance(subsection, list):
                subsection = []
                item[subsection_name] = subsection
            return subsection

    # Create a new subsection
    new_subsection = []
    section_list.append({ subsection_name: new_subsection })
    return new_subsection



# ------------------------------------------------------------
# Build folder-path → section-path mapping from existing nav
# ------------------------------------------------------------
def build_folder_to_section_paths(nav):
    mapping = {}
    entries = flatten_nav_with_paths(nav)
    for section_path, file_path in entries:
        parts = file_path.split("/")[:-1]  # drop filename
        if not parts:
            continue
        # include ALL folder prefixes, including full path
        for i in range(1, len(parts) + 1):
            folder_path = "/".join(parts[:i])
            mapping.setdefault(folder_path, set()).add(tuple(section_path))
        # Add the parent folder itself mapped to its section path
        parent_folder = "/".join(parts)
        mapping.setdefault(parent_folder, set()).add(tuple(section_path[:-1]))
    return mapping


# ------------------------------------------------------------
# Recursive section walker for hierarchical numbering
# ------------------------------------------------------------
def walk_sections(nav, prefix=""):
    mapping = {}
    counter = 1
    for item in nav:
        if isinstance(item, dict):
            name = list(item.keys())[0]
            section_list = item[name]
            number = f"{prefix}{counter}" if prefix else str(counter)
            print(f"{number}. {name}")
            mapping[number] = (name, section_list)
            submap = walk_sections(section_list, prefix=f"{number}.")
            mapping.update(submap)
            counter += 1
    return mapping

def choose_any_section(nav):
    print("\nAvailable sections (including subsections):")
    mapping = walk_sections(nav)
    print("N. Create new top-level section")
    choice = user_input("Choose section number or N: ").strip().lower()
    if choice == "n":
        folder = user_input("Enter folder name to infer section name: ").strip()
        section_name = create_top_level_section(nav, folder)
        return section_name, find_section(nav, section_name)
    if choice not in mapping:
        print("Invalid choice, try again.")
        return choose_any_section(nav)
    return mapping[choice]

# ------------------------------------------------------------
# Subsection / section creation with rename prompts
# ------------------------------------------------------------
def create_subsection(section_list, folder_name):
    inferred = auto_title(folder_name)
    yn = user_input(f"Infer subsection name '{inferred}'? (Y/n): ").strip().lower()
    if yn in ("", "y"):
        name = inferred
    else:
        name = user_input("Enter custom subsection name: ").strip()
    subsection = ensure_subsection(section_list, name)
    return subsection, name

def create_top_level_section(nav, folder_name):
    inferred = auto_title(folder_name)
    yn = user_input(f"Infer top-level section name '{inferred}'? (Y/n): ").strip().lower()
    if yn in ("", "y"):
        name = inferred
    else:
        name = user_input("Enter custom section name: ").strip()
    nav.append({name: []})
    print(f"Created new top-level section '{name}'. Quitting so you can rerun with updated nav.")
    return name

# ------------------------------------------------------------
# Path-based nav matching (no name heuristics)
# ------------------------------------------------------------
def find_nav_paths_for_folder(mapping, folder_path):
    return [list(sp) for sp in mapping.get(folder_path, [])]

# ------------------------------------------------------------
# Bulk add folder contents
# ------------------------------------------------------------
def bulk_add_folder(nav, base_folder_path, section_list):
    print(f"\nBulk add: scanning docs under '{base_folder_path}'...")
    all_docs = scan_docs()
    to_add = [fp for fp in all_docs if fp.startswith(base_folder_path + "/")]
    if not to_add:
        print("No files found to bulk add.")
        return
    print("Files to add:")
    for fp in to_add:
        print(f" - {fp}")
    yn = user_input("Add all these files to the new section? (Y/n): ").strip().lower()
    if yn not in ("", "y"):
        return
    for fp in to_add:
        page_title = infer_page_name(fp)
        section_list.append({ page_title: fp })
        print(f"Added {fp} (page: {page_title})")

# ------------------------------------------------------------
# Main insertion logic
# ------------------------------------------------------------
def insert_file_interactive(nav, folder_mapping, file_path):
    parts = file_path.split("/")
    folder_path = "/".join(parts[:-1]) if len(parts) > 1 else ""
    folder = parts[0] if parts else ""
    subfolder = parts[1] if len(parts) > 2 else None

    print(f"\nFile: {file_path}")

    # If folder path already mapped in nav
    if folder_path:
        nav_paths = find_nav_paths_for_folder(folder_mapping, folder_path)
        if nav_paths:
            if len(nav_paths) == 1:
                sp = nav_paths[0]

                # If the last component is a page, drop it
                last = sp[-1]
                if find_section(nav, last) is None:
                # last is not a section → it's a page → trim it
                    sp = sp[:-1]

                print("We detected an existing nav path for this folder:")
                print("  " + " → ".join(sp))
                use = user_input("Add this file there? (Y/n): ").strip().lower()
                if use in ("", "y"):
                    # walk nav to get section_list
                    section_list = nav
                    for name in sp:
                        result = find_section(section_list, name)

                        if result == "PAGE":
                            # cannot descend into a page → trim logic handles this
                            break

                        if result is None:
                            # missing section → create it
                            subsection, sub_name = create_subsection(section_list, name)
                            section_list = subsection
                        else:
                            # valid section
                            section_list = result

                    page_title = infer_page_name(file_path)
                    section_list.append({ page_title: file_path })
                    print(f"Added {file_path} → {' → '.join(sp)} (page: {page_title})")
                    return
            else:
                print("We detected multiple nav paths for this folder:")
                for i, sp in enumerate(nav_paths, 1):
                    print(f"{i}. " + " → ".join(sp))
                choice = user_input("Choose path number or press Enter to skip: ").strip()
                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(nav_paths):
                        sp = nav_paths[idx]
                        while sp:
                            test = sp[-1]

                            # Walk down to the parent section of `test`
                            probe = nav
                            for name in sp[:-1]:
                                probe = find_section(probe, name)
                                if probe is None:
                                    break

                            # If probe exists AND test is a real section under probe → stop trimming
                            if probe is not None and find_section(probe, test) is not None:
                                break

                            # Otherwise trim
                            sp = sp[:-1]

                        if not sp:
                            print("No valid section found to place this file.")
                            return

                        section_list = nav
                        for name in sp:
                            section_list = find_section(section_list, name)
                        page_title = infer_page_name(file_path)
                        section_list.append({ page_title: file_path })
                        print(f"Added {file_path} → {' → '.join(sp)} (page: {page_title})")
                        return

    # If no nav path for folder, offer to create section/subsection
    if folder_path:
        print(f"No existing nav path for folder '{folder_path}'.")
        print("Options:")
        print("1. Create top-level section for first folder component")
        print("2. Create nested subsection path for this folder")
        print("3. Manual placement")
        choice = user_input("Choose 1/2/3: ").strip()
        if choice == "1":
            section_name = create_top_level_section(nav, folder)
            section_list = find_section(nav, section_name)
            bulk_add_folder(nav, folder, section_list)
            sys.exit(0)
        elif choice == "2":
            # choose parent section manually, then create nested subsections
            parent_name, parent_list = choose_any_section(nav)
            current_list = parent_list
            path_parts = folder_path.split("/")
            for comp in path_parts:
                subsection, sub_name = create_subsection(current_list, comp)
                current_list = subsection
            page_title = infer_page_name(file_path)
            current_list.append({ page_title: file_path })
            print(f"Added {file_path} → {parent_name} → " +
                  " → ".join(auto_title(p) for p in path_parts) +
                  f" (page: {page_title})")
            return
        else:
            # manual placement
            print("Manual placement selected.")
            section_name, section_list = choose_any_section(nav)
            if subfolder:
                want_sub = user_input(f"Create subsection for '{subfolder}' under '{section_name}'? (Y/n): ").strip().lower()
                if want_sub in ("", "y"):
                    subsection, sub_name = create_subsection(section_list, subfolder)
                    page_title = infer_page_name(file_path)
                    subsection.append({ page_title: file_path })
                    print(f"Added {file_path} → {section_name} → {sub_name} (page: {page_title})")
                    return
            page_title = infer_page_name(file_path)
            section_list.append({ page_title: file_path })
            print(f"Added {file_path} → {section_name} (page: {page_title})")
            return
    else:
        # root-level file, manual placement
        print("Root-level file, manual placement.")
        section_name, section_list = choose_any_section(nav)
        page_title = infer_page_name(file_path)
        section_list.append({ page_title: file_path })
        print(f"Added {file_path} → {section_name} (page: {page_title})")

# ------------------------------------------------------------
# Windows-safe TOML write
# ------------------------------------------------------------
def write_toml(data):
    try:
        import tomli_w
    except ImportError as exc:
        raise SystemExit(
            "Writing nav.txt requires tomli-w. Run this script with "
            "`uv run --with tomli-w python sync_nav.py`."
        ) from exc
    out_path = "nav.txt"  # or nav.generated.toml if you prefer
    with open(out_path, "wb") as f:
        tomli_w.dump(data, f)
    print(f"\nWrote updated navigation to {out_path}")


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    print("Loading zensical.toml…")
    data, nav = load_toml_nav()

    print("Scanning docs/…")
    all_docs = scan_docs()
    referenced = flatten_nav(nav)

    missing = sorted(set(all_docs) - set(referenced))
    if not missing:
        print("All .md files are referenced in nav. Nothing to do.")
        return

    print("\nMissing files:")
    for m in missing:
        print(" -", m)

    folder_mapping = build_folder_to_section_paths(nav)

    # -------------------------------
    # QUIT‑AWARE INSERTION LOOP
    # -------------------------------
    try:
        for m in missing:
            insert_file_interactive(nav, folder_mapping, m)

    except SystemExit as e:
        # User typed "quit"
        if str(e) == "quit":
            print("\nQuit command received. Saving partial nav to nav.txt…")
            data["project"]["nav"] = nav
            write_toml(data)
            print("Partial nav saved to nav.txt")
            return
        else:
            raise

    # -------------------------------
    # NORMAL SAVE PATH
    # -------------------------------
    data["project"]["nav"] = nav
    write_toml(data)
    print("\nUpdated zensical.toml successfully.")

if __name__ == "__main__":
    main()"""

let render() = file

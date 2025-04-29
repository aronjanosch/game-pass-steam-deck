#!/usr/bin/env python3
"""
Xbox Cloud Gaming Installer for Steam Deck
Automates the process of setting up Xbox Cloud Gaming through Microsoft Edge.
"""
import os
import sys
import subprocess
import shutil
import re
import hashlib
import time
import urllib.request
import urllib.error
from urllib.parse import urlparse

# Artwork URLs
ARTWORK = {
    "grid": "https://cdn2.steamgriddb.com/grid/02f901e3ff75a8bb581162b5202321e3.png",
    "hero": "https://cdn2.steamgriddb.com/hero/3f3ae0c863fc93011a8e406ee32d5012.png",
    "logo": "https://cdn2.steamgriddb.com/logo/60967da750aba35e0195e947a836d0ef.png",
    "icon": "https://cdn2.steamgriddb.com/icon/164f545c22e17e5e9298b1c84b9e3e1e.png",
}

# Steam Deck paths
HOME_DIR = os.path.expanduser("~")
STEAM_DIR = os.path.join(HOME_DIR, ".local", "share", "Steam")
if not os.path.exists(STEAM_DIR):
    STEAM_DIR = os.path.join(HOME_DIR, ".steam", "steam")
USERDATA_DIR = os.path.join(STEAM_DIR, "userdata")
ARTWORK_DIR = os.path.join(HOME_DIR, "Documents", "xbox_cloud_gaming_artwork")

# Xbox Cloud Gaming launch options
LAUNCH_OPTIONS = '--window-size=1024,640 --force-device-scale-factor=1.25 --device-scale-factor=1.25 --kiosk "https://www.xbox.com/play"'


def log(message):
    """Print a message with timestamp"""
    print(f"[{time.strftime('%H:%M:%S')}] {message}")


def run_command(cmd, check=True, debug=False):
    """Run a shell command and return the output"""
    try:
        log(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=check, capture_output=True, text=True)

        if debug:
            if result.stdout:
                log(f"Command output:\n{result.stdout}")
            if result.stderr:
                log(f"Command error output:\n{result.stderr}")

        return result
    except subprocess.CalledProcessError as e:
        log(f"Error running command: {' '.join(cmd)}")
        log(f"Return code: {e.returncode}")

        if e.stdout:
            log(f"Output:\n{e.stdout}")
        if e.stderr:
            log(f"Error output:\n{e.stderr}")

        return None
    except Exception as e:
        log(f"Unexpected error running command: {' '.join(cmd)}")
        log(f"Error: {str(e)}")
        return None


def download_file(url, destination):
    """Download a file from a URL to a destination using urllib"""
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)

        # Setup request with a user agent to avoid potential blocks
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        }
        req = urllib.request.Request(url, headers=headers)

        # Download the file
        with urllib.request.urlopen(req) as response, open(
            destination, "wb"
        ) as out_file:
            shutil.copyfileobj(response, out_file)

        return True
    except urllib.error.URLError as e:
        log(f"Error downloading {url}: {e}")
        return False
    except Exception as e:
        log(f"Error downloading {url}: {e}")
        return False


def get_steam_users():
    """Get all Steam user IDs from userdata directory"""
    if not os.path.exists(USERDATA_DIR):
        log(f"Steam userdata directory not found: {USERDATA_DIR}")
        return []

    users = []
    for user_id in os.listdir(USERDATA_DIR):
        if user_id != "anonymous" and os.path.isdir(
            os.path.join(USERDATA_DIR, user_id)
        ):
            users.append(user_id)

    return users


def generate_app_id(exe_path, app_name):
    """Generate a Steam app ID for a non-Steam game"""
    # This mimics how Steam generates app IDs for non-Steam games
    # The app ID is a CRC32 hash of the target and app name
    uniqueName = exe_path.encode("utf-8") + app_name.encode("utf-8")
    app_id = hashlib.crc32(uniqueName) & 0xFFFFFFFF
    return app_id


def find_edge_app_id(shortcuts_vdf):
    """Find Microsoft Edge's app ID in shortcuts.vdf"""
    try:
        with open(shortcuts_vdf, "rb") as f:
            content = f.read()

        # Look for "Microsoft Edge" in the binary data using Valve's format
        # SOH + AppName + NUL + Microsoft Edge + NUL
        app_name_pattern = re.compile(rb"\x01AppName\x00(Microsoft Edge|Edge)\x00")
        # STX + appid + NUL + [4 bytes of appid]
        app_id_pattern = re.compile(rb"\x02appid\x00(.{4})")

        matches = list(app_name_pattern.finditer(content))

        for match in matches:
            # Find the appid before this match
            # We need to look back to find the start of this entry
            # Typically each entry starts with an index followed by appid
            start_pos = max(0, match.start() - 200)
            segment = content[start_pos : match.start()]

            app_id_match = app_id_pattern.search(segment)
            if app_id_match:
                app_id_bytes = app_id_match.group(1)
                app_id = int.from_bytes(app_id_bytes, byteorder="little")
                return app_id

        return None
    except Exception as e:
        log(f"Error finding Edge app ID: {e}")
        return None


def modify_shortcuts_vdf(
    shortcuts_vdf, edge_app_id, new_name="Xbox Cloud Gaming (Beta)"
):
    """Modify shortcuts.vdf to update Edge's name and launch options"""
    try:
        # Make a backup of the file
        backup_file = f"{shortcuts_vdf}.bak"
        shutil.copy2(shortcuts_vdf, backup_file)

        with open(shortcuts_vdf, "rb") as f:
            content = f.read()

        # According to Valve's documentation, we need to find the entry with this pattern:
        # SOH + AppName + NUL + Microsoft Edge + NUL
        edge_pattern = re.compile(rb"\x01AppName\x00(Microsoft Edge|Edge)\x00")
        matches = list(edge_pattern.finditer(content))

        if matches:
            for match in matches:
                old_name = match.group(1)
                # Replace the name
                content = content.replace(
                    b"\x01AppName\x00" + old_name + b"\x00",
                    b"\x01AppName\x00" + new_name.encode("utf-8") + b"\x00",
                )

                # Find the LaunchOptions section for this entry and add our options
                # We need to look backward to find the entry ID, then forward to find LaunchOptions
                start_pos = max(0, match.start() - 200)
                entry_segment = content[start_pos : match.start() + 500]

                # Add launch options if section exists
                launch_options_pattern = re.compile(
                    rb"\x01LaunchOptions\x00([^\x00]*)\x00"
                )
                launch_match = launch_options_pattern.search(entry_segment)
                if launch_match:
                    current_options = launch_match.group(1)
                    # Only add our options if they're not already there
                    if b'--kiosk "https://www.xbox.com/play"' not in current_options:
                        new_options = (
                            current_options + b" " + LAUNCH_OPTIONS.encode("utf-8")
                        )
                        content = content.replace(
                            b"\x01LaunchOptions\x00" + current_options + b"\x00",
                            b"\x01LaunchOptions\x00" + new_options + b"\x00",
                        )
                        log(f"Updated launch options for {new_name}")

        # Write the modified content back
        with open(shortcuts_vdf, "wb") as f:
            f.write(content)

        log(f"Updated shortcuts.vdf - renamed Edge to '{new_name}'")
        return True
    except Exception as e:
        log(f"Error modifying shortcuts.vdf: {e}")
        # Restore backup if something went wrong
        if os.path.exists(backup_file):
            shutil.copy2(backup_file, shortcuts_vdf)
        return False


def add_shortcut_to_steam(shortcuts_vdf, user_id):
    """Add Microsoft Edge as a shortcut to Steam by directly modifying shortcuts.vdf"""
    try:
        debug_mode = "--debug" in sys.argv

        # Make a backup
        backup_file = f"{shortcuts_vdf}.bak"
        shutil.copy2(shortcuts_vdf, backup_file)

        if debug_mode:
            log(f"Created backup of shortcuts.vdf at {backup_file}")

            # In debug mode, dump the file contents
            with open(shortcuts_vdf, "rb") as f:
                content = f.read()
            log(f"Original shortcuts.vdf size: {len(content)} bytes")

            # Look for shortcuts section
            if b"\x00shortcuts\x00" in content:
                log("Found 'shortcuts' section in the file")
            else:
                log("WARNING: Could not find 'shortcuts' section in shortcuts.vdf")

        # Get Edge Flatpak information
        flatpak_info = run_command(
            ["flatpak", "info", "com.microsoft.Edge"], check=False, debug=debug_mode
        )
        if not flatpak_info or flatpak_info.returncode != 0:
            log("Could not get Flatpak info for Microsoft Edge")
            if debug_mode and flatpak_info:
                log(f"Flatpak info error: {flatpak_info.stderr}")
            return False

        # Get the Edge executable path
        edge_exe = "/usr/bin/flatpak"
        edge_launch_args = "run com.microsoft.Edge"
        edge_name = "Microsoft Edge"

        if debug_mode:
            log(f"Using exe path: {edge_exe}")
            log(f"Using launch args: {edge_launch_args}")

        # Generate a unique app ID
        app_id = generate_app_id(edge_exe.encode(), edge_name.encode())
        if debug_mode:
            log(f"Generated app ID: {app_id}")

        # Read the existing shortcuts.vdf
        with open(shortcuts_vdf, "rb") as f:
            content = f.read()

        # Determine the next available index
        index_pattern = re.compile(rb"\x00(\d+)\x00")
        indices = [int(m.group(1)) for m in index_pattern.finditer(content)]
        next_index = "0" if not indices else str(max([int(i) for i in indices]) + 1)

        if debug_mode:
            log(f"Found existing indices: {indices}")
            log(f"Using next index: {next_index}")

        # Build the new shortcut entry based on Valve's format
        # Format follows the structure documented by Valve
        new_entry = (
            b"\x00"
            + next_index.encode()
            + b"\x00"
            + b"\x02appid\x00"
            + app_id.to_bytes(4, byteorder="little")
            + b"\x00\x00\x00\x00"
            + b"\x01AppName\x00"
            + edge_name.encode()
            + b"\x00"
            + b'\x01Exe\x00"'
            + edge_exe.encode()
            + b'"\x00'
            + b'\x01StartDir\x00"'
            + os.path.dirname(edge_exe).encode()
            + b'"\x00'
            + b"\x01icon\x00\x00"
            + b"\x01ShortcutPath\x00\x00"
            + b"\x01LaunchOptions\x00"
            + edge_launch_args.encode()
            + b"\x00"
            + b"\x02IsHidden\x00\x00\x00\x00\x00\x00"
            + b"\x02AllowDesktopConfig\x00\x01\x00\x00\x00"
            + b"\x02AllowOverlay\x00\x01\x00\x00\x00"
            + b"\x02OpenVR\x00\x00\x00\x00\x00"
            + b"\x02Devkit\x00\x00\x00\x00\x00"
            + b"\x01DevkitGameID\x00\x00"
            + b"\x01DevkitOverrideAppID\x00\x00"
            + b"\x02LastPlayTime\x00\x00\x00\x00\x00"
            + b"\x01FlatpakAppID\x00com.microsoft.Edge\x00"
            + b"\x00tags\x00"
            + b"\x08\x08"
        )

        if debug_mode:
            log(f"Created new entry with size: {len(new_entry)} bytes")

        # Check if shortcuts section exists
        if b"\x00shortcuts\x00" in content:
            if debug_mode:
                log("Found shortcuts section, looking for insertion point")

            # Insert our new entry before the final BS BS
            if content.endswith(b"\x08\x08"):
                if debug_mode:
                    log("File ends with BS BS, replacing them")

                # Remove the last two BS characters
                content = content[:-2]
                # Add our entry and the closing BS BS
                content = content + new_entry + b"\x08\x08"
            else:
                # If not ending with BS BS, insert before the last BS (if it exists)
                last_bs_pos = content.rfind(b"\x08")
                if last_bs_pos > 0:
                    if debug_mode:
                        log(
                            f"Found last BS at position {last_bs_pos}, inserting before it"
                        )
                    content = content[:last_bs_pos] + new_entry + content[last_bs_pos:]
                else:
                    # Append to the end if we can't find a good insertion point
                    if debug_mode:
                        log(
                            "Could not find a good insertion point, appending to the end"
                        )
                    content = content + new_entry
        else:
            # Create a new shortcuts section
            if debug_mode:
                log("No shortcuts section found, creating a new one")
            content = b"\x00shortcuts\x00" + new_entry + b"\x08\x08"

        # Write the modified content back
        with open(shortcuts_vdf, "wb") as f:
            f.write(content)

        if debug_mode:
            log(f"Wrote {len(content)} bytes to shortcuts.vdf")

        log(f"Added Microsoft Edge to Steam with app ID: {app_id}")
        return True

    except Exception as e:
        log(f"Error adding Edge to Steam: {e}")

        if "--debug" in sys.argv:
            import traceback

            traceback.print_exc()

        # Restore backup if something went wrong
        if os.path.exists(backup_file):
            shutil.copy2(backup_file, shortcuts_vdf)
            log("Restored backup of shortcuts.vdf")

        return False


def add_edge_to_steam():
    """
    Add Microsoft Edge to Steam
    Returns the app ID if successful, None otherwise
    """
    log("Checking if Edge is already in Steam...")

    # Check existing shortcuts.vdf files
    for user_id in get_steam_users():
        shortcuts_vdf = os.path.join(USERDATA_DIR, user_id, "config", "shortcuts.vdf")
        if os.path.exists(shortcuts_vdf):
            edge_app_id = find_edge_app_id(shortcuts_vdf)
            if edge_app_id:
                log(f"Microsoft Edge is already in Steam with app ID: {edge_app_id}")
                return edge_app_id, user_id

    debug_mode = "--debug" in sys.argv
    log("Microsoft Edge not found in Steam. Attempting to add it automatically...")

    # Try to add Edge to Steam automatically
    for user_id in get_steam_users():
        shortcuts_vdf = os.path.join(USERDATA_DIR, user_id, "config", "shortcuts.vdf")
        if os.path.exists(shortcuts_vdf):
            if debug_mode:
                log(f"Found shortcuts.vdf at {shortcuts_vdf}")
                log(f"Attempting to add Edge for user {user_id}")

            if add_shortcut_to_steam(shortcuts_vdf, user_id):
                # Check if Edge was added successfully
                edge_app_id = find_edge_app_id(shortcuts_vdf)
                if edge_app_id:
                    log(f"Successfully added Edge to Steam with app ID: {edge_app_id}")
                    return edge_app_id, user_id

    # If automatic addition failed, ask user to do it manually
    log("Automatic addition failed. Please add Edge to Steam manually:")
    log("1. Select Application Launcher > Internet")
    log("2. Right-click Microsoft Edge and select 'Add to Steam'")
    log(
        "3. In the 'Add a Game' window, check Microsoft Edge and click 'Add Selected Programs'"
    )

    # Wait for user to add Edge to Steam
    input("Press Enter after you've added Microsoft Edge to Steam...")

    # Check again for Edge in Steam
    for user_id in get_steam_users():
        shortcuts_vdf = os.path.join(USERDATA_DIR, user_id, "config", "shortcuts.vdf")
        if os.path.exists(shortcuts_vdf):
            edge_app_id = find_edge_app_id(shortcuts_vdf)
            if edge_app_id:
                log(f"Found Microsoft Edge in Steam with app ID: {edge_app_id}")
                return edge_app_id, user_id

    log(
        "Could not find Microsoft Edge in Steam after manual addition. Continuing anyway..."
    )
    return None, None


def update_localconfig_vdf(user_id, edge_app_id, new_name="Xbox Cloud Gaming (Beta)"):
    """Update localconfig.vdf to set the launch options and name for the shortcut"""
    if not user_id or not edge_app_id:
        log("Cannot update localconfig.vdf: Missing user ID or app ID")
        return False

    try:
        localconfig_path = os.path.join(
            USERDATA_DIR, user_id, "config", "localconfig.vdf"
        )
        if not os.path.exists(localconfig_path):
            log(f"localconfig.vdf not found at {localconfig_path}")
            return False

        # Make a backup
        backup_file = f"{localconfig_path}.bak"
        shutil.copy2(localconfig_path, backup_file)

        with open(localconfig_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Find the section for our app ID
        app_section_pattern = re.compile(
            rf'"({edge_app_id}|Non-Steam-App_{edge_app_id})"\\s*{{'
        )
        match = app_section_pattern.search(content)

        if match:
            # Get the section start position
            section_start = match.start()

            # Find where the section ends (next closing brace at the same level)
            brace_count = 1
            section_end = section_start

            for i in range(section_start + len(match.group(0)), len(content)):
                if content[i] == "{":
                    brace_count += 1
                elif content[i] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        section_end = i + 1
                        break

            # Extract the section
            section = content[section_start:section_end]

            # Update the LaunchOptions in this section
            if '"LaunchOptions"' in section:
                # Update existing LaunchOptions
                updated_section = re.sub(
                    r'"LaunchOptions"\s*"([^"]*)"',
                    f'"LaunchOptions" "\\1 {LAUNCH_OPTIONS}"',
                    section,
                )
            else:
                # Add LaunchOptions if not present
                updated_section = section.replace(
                    "{", '{\n\t\t"LaunchOptions"\t\t"' + LAUNCH_OPTIONS + '"', 1
                )

            # Replace the section in the content
            content = content[:section_start] + updated_section + content[section_end:]

            # Write the updated content back
            with open(localconfig_path, "w", encoding="utf-8") as f:
                f.write(content)

            log(f"Updated launch options in localconfig.vdf")
            return True
        else:
            log(f"Could not find entry for app ID {edge_app_id} in localconfig.vdf")

            # Fallback to manual update
            log("Please update the launch options manually:")
            log("1. Open Steam and go to your Library")
            log(
                "2. Right-click on Microsoft Edge/Xbox Cloud Gaming and select Properties"
            )
            log("3. Under LAUNCH OPTIONS, add this after @@u @@:")
            log(f"   {LAUNCH_OPTIONS}")

            input("Press Enter after you've updated the launch options...")
            return True

    except Exception as e:
        log(f"Error updating localconfig.vdf: {e}")
        # Restore backup if something went wrong
        if os.path.exists(backup_file):
            shutil.copy2(backup_file, localconfig_path)

        # Fallback to manual update
        log("Please update the launch options manually:")
        log("1. Open Steam and go to your Library")
        log("2. Right-click on Microsoft Edge/Xbox Cloud Gaming and select Properties")
        log("3. Under LAUNCH OPTIONS, add this after @@u @@:")
        log(f"   {LAUNCH_OPTIONS}")

        input("Press Enter after you've updated the launch options...")
        return True


def apply_artwork(edge_app_id, user_id):
    """Download and apply Xbox Cloud Gaming artwork"""
    if not edge_app_id or not user_id:
        log("Cannot apply artwork: Missing app ID or user ID")
        return False

    # Create artwork directory
    os.makedirs(ARTWORK_DIR, exist_ok=True)

    # Download artwork
    log("Downloading Xbox Cloud Gaming artwork...")
    artwork_files = {}
    for art_type, url in ARTWORK.items():
        file_ext = os.path.splitext(url)[1]
        destination = os.path.join(
            ARTWORK_DIR, f"xbox_cloud_gaming_{art_type}{file_ext}"
        )

        if download_file(url, destination):
            artwork_files[art_type] = destination
            log(f"Downloaded {art_type} artwork")
        else:
            log(f"Failed to download {art_type} artwork")

    # Apply artwork to Steam
    grid_dir = os.path.join(USERDATA_DIR, user_id, "config", "grid")
    os.makedirs(grid_dir, exist_ok=True)

    # Define how to apply each artwork type
    artwork_mapping = {
        "grid": {"suffix": "p", "steam_name": "library_600x900_2x.jpg"},
        "hero": {"suffix": "_hero", "steam_name": "library_hero.jpg"},
        "logo": {"suffix": "_logo", "steam_name": "logo.png"},
        "icon": {"suffix": "", "steam_name": "header.jpg"},
    }

    # Apply each artwork
    for art_type, file_path in artwork_files.items():
        if art_type not in artwork_mapping:
            continue

        suffix = artwork_mapping[art_type]["suffix"]
        file_ext = os.path.splitext(file_path)[1]

        # Apply to Steam
        dest_path = os.path.join(grid_dir, f"{edge_app_id}{suffix}{file_ext}")
        shutil.copy(file_path, dest_path)
        log(f"Applied {art_type} artwork to {dest_path}")

        # For legacy naming (important for banners)
        if art_type == "grid":
            legacy_id = (int(edge_app_id) << 32) | 0x02000000
            legacy_path = os.path.join(grid_dir, f"{legacy_id}{suffix}{file_ext}")
            shutil.copy(file_path, legacy_path)
            log(f"Applied legacy {art_type} artwork to {legacy_path}")

    return True


def main():
    """Main installer function"""
    # Parse command line arguments
    debug_mode = "--debug" in sys.argv

    print(
        """
╔═══════════════════════════════════════════════════╗
║         Xbox Cloud Gaming Installer v1.0          ║
║              for Steam Deck                       ║
╚═══════════════════════════════════════════════════╝
    """
    )

    if debug_mode:
        log("Debug mode enabled - showing detailed output")

    # Check if we're on Linux
    if sys.platform != "linux":
        log("Warning: This script is designed for Steam Deck (Linux)")

    # Create output directory
    os.makedirs(ARTWORK_DIR, exist_ok=True)

    # Check for Steam running
    steam_processes = run_command(["pgrep", "steam"], check=False, debug=debug_mode)
    if steam_processes and steam_processes.returncode == 0:
        log("Steam is currently running. For best results, Steam should be closed.")
        answer = input("Would you like to close Steam now? (y/n): ")
        if answer.lower() == "y":
            log("Closing Steam...")
            run_command(["killall", "steam"], check=False, debug=debug_mode)
            time.sleep(2)  # Give Steam time to close

    # Step 1: Install Microsoft Edge
    log("Checking if Microsoft Edge is installed...")
    edge_check = run_command(
        ["flatpak", "list", "--app"], check=False, debug=debug_mode
    )

    if edge_check and "com.microsoft.Edge" in edge_check.stdout:
        log("Microsoft Edge is already installed")
    else:
        log("Installing Microsoft Edge via Flatpak...")
        # Use --user flag to install for the current user only
        install_result = run_command(
            ["flatpak", "install", "flathub", "com.microsoft.Edge", "-y", "--user"],
            check=False,
            debug=debug_mode,
        )

        if install_result and install_result.returncode == 0:
            log("Microsoft Edge installed successfully")
        else:
            log("Failed to install Microsoft Edge")
            log("Please try installing it manually with this command:")
            log("flatpak install flathub com.microsoft.Edge -y --user")
            return

    # Step 2: Configure Edge for udev access
    log("Configuring Edge for controller support...")
    udev_result = run_command(
        [
            "flatpak",
            "--user",
            "override",
            "--filesystem=/run/udev:ro",
            "com.microsoft.Edge",
        ],
        check=False,
        debug=debug_mode,
    )
    if udev_result and udev_result.returncode == 0:
        log("Edge configured for controller support")
    else:
        log("Failed to configure Edge for controller support")
        if debug_mode and udev_result:
            log(f"Error details: {udev_result.stderr}")
        return

    # Step 3: Add Edge to Steam and find its app ID
    edge_app_id, user_id = add_edge_to_steam()

    # Step 4: Rename Edge to Xbox Cloud Gaming and update launch options
    if edge_app_id and user_id:
        log(f"Configuring Edge (app ID: {edge_app_id}) for Xbox Cloud Gaming...")

        # Update shortcuts.vdf to rename Edge
        shortcuts_vdf = os.path.join(USERDATA_DIR, user_id, "config", "shortcuts.vdf")
        if os.path.exists(shortcuts_vdf):
            modify_shortcuts_vdf(shortcuts_vdf, edge_app_id)

        # Also try to update localconfig.vdf for launch options
        update_localconfig_vdf(user_id, edge_app_id)

    # Step 5: Download and apply artwork
    if edge_app_id and user_id:
        log("Setting up Xbox Cloud Gaming artwork...")
        apply_artwork(edge_app_id, user_id)
        log("Artwork applied successfully")

    # Final instructions
    print(
        """
╔═══════════════════════════════════════════════════╗
║                  Setup Complete!                  ║
╚═══════════════════════════════════════════════════╝

To complete setup:

1. Start Steam
2. In Steam, go to Library and find Xbox Cloud Gaming (Beta)
3. Right-click and select Manage > Controller Layout
4. Select BROWSE CONFIGS
5. Under Templates, select "Gamepad with Mouse Trackpad"
6. Apply the configuration and click DONE

You can now return to Gaming Mode and enjoy Xbox Cloud Gaming!
    """
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSetup canceled by user")
    except Exception as e:
        print(f"Error: {str(e)}")
        print("Please complete setup manually")

        # Print traceback in debug mode
        if "--debug" in sys.argv:
            import traceback

            traceback.print_exc()

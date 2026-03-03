import sqlite3
import os
import re

# --- CONFIG ---
DB_FILE = os.path.expanduser("~/Fortress-Prime/nas_master_index.db")

def hunt_github():
    print(f"🐙 HUNTING FOR GITHUB REMOTES (The Off-Site Backup)...")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # 1. Find Git Config Files
    # We look for files named 'config' that are inside a '.git' folder
    print("\n🔍 Scanning 5 million files for .git configurations...")
    c.execute("SELECT path FROM files WHERE path LIKE '%/.git/config'")
    configs = c.fetchall()
    
    found_urls = set()
    
    print(f"   Found {len(configs)} local git repositories. Analyzing remotes...")
    
    for row in configs:
        config_path = row[0]
        # We need to read the actual file content to find the URL
        try:
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    # Regex to find github URLs (ssh or https)
                    # Matches: git@github.com:User/Repo.git OR https://github.com/User/Repo.git
                    matches = re.findall(r'(github\.com[:/][\w\-\.]+/[\w\-\.]+)', content)
                    for m in matches:
                        # Clean up the URL
                        clean_url = m.replace("github.com:", "github.com/")
                        if not clean_url.startswith("http"):
                            clean_url = "https://" + clean_url
                        found_urls.add(clean_url)
        except:
            pass

    # 2. Check Global .gitconfig (User identity)
    c.execute("SELECT path FROM files WHERE filename = '.gitconfig'")
    globals_list = c.fetchall()
    users = set()
    for row in globals_list:
        try:
            with open(row[0], 'r', errors='ignore') as f:
                content = f.read()
                # Find user = Name or email = email
                name = re.search(r'name\s*=\s*(.*)', content)
                email = re.search(r'email\s*=\s*(.*)', content)
                if name: users.add(f"Name: {name.group(1)}")
                if email: users.add(f"Email: {email.group(1)}")
        except: pass

    # 3. REPORT
    print("\n" + "="*50)
    print("✅ GITHUB RECONNAISSANCE REPORT")
    print("="*50)
    
    if users:
        print("\n👤 GIT IDENTITIES FOUND:")
        for u in users: print(f"   - {u}")
    
    if found_urls:
        print(f"\n🔗 FOUND {len(found_urls)} REMOTE REPOSITORIES:")
        for url in sorted(list(found_urls)):
            print(f"   🌍 {url}")
            # Highlight AI projects
            if any(x in url.lower() for x in ['ai', 'gpt', 'model', 'train', 'bot', 'scraper']):
                print(f"      ^^^ 🧠 POTENTIAL AI PROJECT")
    else:
        print("\n❌ No GitHub remotes found. You might have used GitLab, Bitbucket, or no remote.")

    conn.close()

if __name__ == "__main__":
    hunt_github()

import asyncio
import aiohttp
import sys
import dotenv
import os
import re
import subprocess
from markdown import markdown
from shutil import rmtree, copy, copytree, ignore_patterns, make_archive
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
import ai_diffusion
from ai_diffusion.resources import update_model_checksums

sys.path.append(str(Path(__file__).parent))
import translation

root = Path(__file__).parent.parent
package_dir = root / "scripts" / ".package"


def convert_markdown_to_html(markdown_file: Path, html_file: Path):
    with open(markdown_file, "r", encoding="utf-8") as f:
        text = f.read()
    html = markdown(text, extensions=["fenced_code", "codehilite"])
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html)


def _read_release_notes():
    """Return (title, version, body_text) from release_notes.md, or (None, None, None)."""
    release_notes_file = root / "release_notes.md"
    if not release_notes_file.exists():
        return None, None, None

    text = release_notes_file.read_text(encoding="utf-8")
    lines = [line.rstrip() for line in text.splitlines()]

    title = None
    declared_version = None
    body_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("title:"):
            title = stripped.split(":", 1)[1].strip() or None
            continue
        if lower.startswith("version:"):
            declared_version = stripped.split(":", 1)[1].strip() or None
            continue
        body_lines.append(line)

    body_text = "\n".join(body_lines).strip() or None
    return title, declared_version, body_text


def _update_file_version(path: Path, pattern: str, replacement: str):
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, replacement, text, count=1)
    if count == 0:
        raise RuntimeError(f"Failed to update version in {path}")
    path.write_text(new_text, encoding="utf-8")


def get_release_metadata(sync_code_version: bool = True):
    """Return (version, release_name, release_body) and optionally sync code version.

    - Version is primarily taken from release_notes.md's ``Version:`` line.
    - If missing, falls back to ai_diffusion.__version__.
    - When sync_code_version is True and a Version is declared, update
      ai_diffusion/__init__.py and ai_diffusion/resources.py to that value.
    """
    title, declared_version, body_text = _read_release_notes()

    version = ai_diffusion.__version__

    if declared_version:
        if sync_code_version and declared_version != version:
            init_path = root / "ai_diffusion" / "__init__.py"
            resources_path = root / "ai_diffusion" / "resources.py"

            print(f"Updating plugin version from {version} to {declared_version}")
            _update_file_version(
                init_path,
                r'(__version__\s*=\s*")[^"]*(")',
                rf'\1{declared_version}\2',
            )
            _update_file_version(
                resources_path,
                r'(version\s*=\s*")[^"]*(")',
                rf'\1{declared_version}\2',
            )

            # Keep the in-memory modules in sync as well.
            ai_diffusion.__version__ = declared_version
            try:
                import ai_diffusion.resources as resources_module

                resources_module.version = declared_version
            except Exception:
                pass

            version = declared_version
        else:
            version = declared_version

    release_name = f"krita_ai_diffusion {version}"
    if title:
        release_name = f"{title} ({version})"

    release_body = body_text or f"Version {version}"
    return version, release_name, release_body


def update_server_requirements():
    subprocess.run(
        [
            "uv",
            "pip",
            "compile",
            "scripts/server_requirements.in",
            "--no-deps",
            "--no-annotate",
            "--universal",
            "--upgrade",
            "--quiet",
            "--only-binary",
            ":all:",
            "--no-binary",
            "svglib",
            "--no-binary",
            "fvcore",
            "-o",
            "ai_diffusion/server_requirements.txt",
        ],
        cwd=root,
        check=True,
    )


def precheck():
    translation.update_template()
    translation.update_all()

    update_model_checksums(root / "scripts" / "downloads")


def build_package():
    version, _, _ = get_release_metadata(sync_code_version=True)
    package_name = f"krita_ai_diffusion-{version}"

    precheck()

    rmtree(package_dir, ignore_errors=True)
    package_dir.mkdir()
    copy(root / "ai_diffusion.desktop", package_dir)

    plugin_src = root / "ai_diffusion"
    plugin_dst = package_dir / "ai_diffusion"

    def ignore(path, names):
        return ignore_patterns(".*", "*.pyc", "__pycache__", "debugpy")(path, names)

    copytree(plugin_src, plugin_dst, ignore=ignore)
    copy(root / "scripts" / "download_models.py", plugin_dst)
    copy(root / "LICENSE", plugin_dst)
    convert_markdown_to_html(root / "README.md", plugin_dst / "manual.html")

    make_archive(str(root / package_name), "zip", package_dir)

    # Do this afterwards to not include untested changes in the package
    # Option 1: test the dependency changes and do another package build
    # Option 2: revert the dependency changes, keep stable version for now
    update_server_requirements()


async def publish_package(package_path: Path, target: str):
    # Load environment from .env, then optionally override with .env.local
    dotenv.load_dotenv(root / ".env")
    dotenv.load_dotenv(root / ".env.local", override=True)
    repo = os.environ.get("PLUGIN_REPO")
    token = os.environ.get("GITHUB_TOKEN")

    if not repo or not token:
        raise RuntimeError(
            "PLUGIN_REPO and GITHUB_TOKEN must be set in .env.local to publish the package."
        )

    owner, name = repo.split("/", 1)

    version, release_name, release_body = get_release_metadata(sync_code_version=True)
    tag_name = f"v{version}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        release_url = f"https://api.github.com/repos/{owner}/{name}/releases"
        release_payload = {
            "tag_name": tag_name,
            "name": release_name,
            "body": release_body,
            "draft": False,
            "prerelease": False,
        }

        async with session.post(release_url, json=release_payload) as response:
            if response.status == 201:
                release = await response.json()
            elif response.status == 422:
                # Release likely already exists, fetch it by tag
                async with session.get(f"{release_url}/tags/{tag_name}") as get_response:
                    if get_response.status != 200:
                        raise RuntimeError(
                            f"Failed to fetch existing release: {get_response.status}",
                            await get_response.text(),
                        )
                    release = await get_response.json()
            else:
                raise RuntimeError(
                    f"Failed to create release: {response.status}", await response.text()
                )

        upload_url = release["upload_url"].split("{", 1)[0]
        archive_data = package_path.read_bytes()
        upload_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/zip",
            "Accept": "application/vnd.github+json",
        }

        async with aiohttp.ClientSession(headers=upload_headers) as upload_session:
            async with upload_session.post(
                upload_url, params={"name": package_path.name}, data=archive_data
            ) as upload_response:
                if upload_response.status not in (200, 201):
                    raise RuntimeError(
                        f"Failed to upload asset: {upload_response.status}",
                        await upload_response.text(),
                    )
                asset = await upload_response.json()
                print("Uploaded asset:", asset.get("browser_download_url"))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"

    if cmd == "build":
        version, _, _ = get_release_metadata(sync_code_version=True)
        package_name = f"krita_ai_diffusion-{version}"
        print("Building package", root / package_name)
        build_package()

    elif cmd == "publish":
        version, _, _ = get_release_metadata(sync_code_version=True)
        package_name = f"krita_ai_diffusion-{version}"
        package = root / f"{package_name}.zip"
        print("Publishing package", str(package))
        asyncio.run(publish_package(package, "github"))

    elif cmd == "check":
        print("Performing precheck without building")
        precheck()

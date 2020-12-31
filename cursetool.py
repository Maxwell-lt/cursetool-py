from urllib.request import Request, urlopen
from urllib.parse import unquote
import json
import re
from typing import List
import os.path
from http.client import HTTPResponse
import sys
import logging
from hashlib import md5, sha256
from textwrap import dedent
from time import sleep

BASE_URL = "https://addons-ecs.forgesvc.net/api/v2"

def get_response_with_retry(request: Request, parse_json=True):
    logger = logging.getLogger("get_response_with_retry")
    attempt_counter = 0
    while True:
        attempt_counter += 1
        try:
            response_data = urlopen(request).read().decode("utf-8")
        except:
            logger.info("Request to URL {url} failed on attempt number {count}".format(url = request.get_full_url(), count = attempt_counter))
            sleep(1)
            continue

        if not parse_json:
            return response_data

        try:
            return json.loads(response_data)
        except json.JSONDecodeError as e:
            logger.info("Failed to decode JSON response after request to {url} on attempt number {count}".format(url = request.get_full_url(), count = attempt_counter))
            sleep(1)

def get_addon_info(projectID: int):
    request = Request("{baseurl}/addon/{projectID}".format(baseurl = BASE_URL, projectID = projectID), headers={"Content-Type": "application/x-www-form-urlencoded"}, method="GET")
    response = get_response_with_retry(request)
    return response

def get_download_url(projectID: int, fileID: int) -> str:
    request = Request("{baseurl}/addon/{projectID}/file/{fileID}/download-url".format(baseurl = BASE_URL, projectID = projectID, fileID = fileID), headers={"Content-Type": "application/x-www-form-urlencoded"}, method="GET")
    download_url = get_response_with_retry(request, parse_json=False)

    # If the download url is to edge.forgecdn.net, we want to hit media.forgecdn.net instead.
    # If this is to edge-service.overwolf.wtf, we don't want to do the string replacement.
    if "edge.forgecdn" in download_url:
        return download_url.replace("edge", "media").replace("+", "%2B").replace(" ", "%20")
    else:
        return download_url

def get_slug_from_addon_info(addon_info) -> str:
    website_url = addon_info["websiteUrl"]
    # Get text after last "/" character
    return re.search(".*\/(.*)$", website_url).groups()[0]

def read_curse_manifest(filename: str):
    with open(filename, 'r') as file:
        manifest = json.load(file)
    return manifest

def get_file_info(download_url):
    logger = logging.getLogger("get_file_info")
    logger.info("Downloading file from {url}".format(url = download_url))
    attempt_counter = 0
    while True:
        attempt_counter += 1
        try:
            response = urlopen(download_url)
            if response.status == 200:
                break
        except:
            logger.info("Encountered error downloading file from URL {url} on attempt count {count}".format(url = download_url, count = attempt_counter))
            sleep(1)

    # Potential memory usage issue with large .jar files.
    file_data = response.read()
    file_size = len(file_data)
    md5_hash = md5(file_data).hexdigest()
    sha256_hash = sha256(file_data).hexdigest()
    # Files don't seem to have a content-disposition header, so we just extract the text after the last "/" character
    filename_encoded = re.search(".*\/(.*)$", download_url).groups()[0]
    filename = unquote(filename_encoded)
    logger.info("Finished processing {filename}".format(filename = filename))

    return filename, filename_encoded, md5_hash, sha256_hash, file_size

def generate_nix_mod_entry(projectID: int, fileID: int):
    logger = logging.getLogger("generate_nix_mod_entry")
    logger.info("Fetching data for project {projectID}, file {fileID}".format(projectID = projectID, fileID = fileID))
    addon_info = get_addon_info(projectID)
    download_url = get_download_url(projectID, fileID)
    slug = get_slug_from_addon_info(addon_info)

    filename, filename_encoded, md5_hash, sha256_hash, file_size = get_file_info(download_url)
    return """"{slug}" = {{"title"="{title}"; "name"="{slug}"; "id"="{id}"; "side"="both"; "required"=true; "default"=true; "deps"=[]; "filename"="{filename}"; "encoded"="{encoded}"; "page"=""; "src"="{download_url}"; "type"="remote"; "size"={size}; "md5"="{md5}"; "sha256"="{sha256}";}};"""\
            .format(slug = slug, title = addon_info["name"], id = projectID, filename = filename, encoded = filename_encoded, download_url = download_url, size = file_size, md5 = md5_hash, sha256 = sha256_hash)

def write_nix_manifest(mods: List[str], mc_version, filename):
    with open(filename, 'w') as f:
        f.write(dedent("""
        {{
            "version" = "{version}";
            "imports" = [];
            "mods" = {{
                {modlist}
            }};
        }}
        """).format(version = mc_version, modlist = "\n".join(mods)))

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise Exception("Must provide two parameters: input file and output file")

    logging.basicConfig(level=logging.DEBUG, format='%(name)s - %(levelname)s - %(message)s')

    manifest_path, out_path = sys.argv[1:3]
    logging.info("Reading Curse manifest at {filepath}...".format(filepath = manifest_path))

    manifest = read_curse_manifest(manifest_path)
    mod_list = list()
    logging.info("Retrieving mod data...")
    for mod in manifest["files"]:
        mod_list.append(generate_nix_mod_entry(mod["projectID"], mod["fileID"]))
    
    logging.info("Writing .nix manifest to {filepath}...".format(filepath = out_path))
    write_nix_manifest(mod_list, manifest["minecraft"]["version"], out_path)

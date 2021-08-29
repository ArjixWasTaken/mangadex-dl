import requests
import time
import os
import sys
import re
import json
import html
import zipfile
import argparse
import shutil
from multiprocessing.pool import ThreadPool
import random

__VERSION__ = "0.6.0"
# Original from: https://github.com/frozenpandaman/mangadex-dl/blob/master/mangadex-dl.py
# By Eli Fessler (https://github.com/frozenpandaman)
# Modified by Arjix (https://github.com/ArjixWasTaken)


download_dir = "./mangadex-dl"
if not os.path.isdir(download_dir):
    os.makedirs(download_dir)

def get_safe(link, count=0, method=requests.get, **kwargs):
    time.sleep(1)

    if count == 30:
        raise Exception("API fails to respond or API ratelimit was not reset.")

    r = method(link, **kwargs)
    if r.status_code == 200:
        return r.json()
    else:
        time.sleep(5)
        return get_safe(link, count=count+1, method=method, **kwargs)


def get_safe_binary_data(link, count=0, method=requests.get, **kwargs):
    if count == 30:
        raise Exception("API fails to respond or API ratelimit was not reset.")

    r = method(link,  **kwargs)
    if r.status_code == 200:
        return r.content
    else:
        time.sleep(5)
        return get_safe_binary_data(link, count=count+1, method=method, **kwargs)


def pad_filename(str):
    digits = re.compile('(\\d+)')
    pos = digits.search(str)
    if pos:
        return str[1:pos.start()] + pos.group(1).zfill(3) + str[pos.end():]
    else:
        return str


def float_conversion(tupl):
    try:
        x = float(tupl[0])  # (chap_num, chap_uuid)
    except ValueError:  # empty string for oneshot
        x = 0
    return x


def zpad(num):
    if "." in num:
        parts = num.split('.')
        return "{}.{}".format(parts[0].zfill(3), parts[1])
    else:
        return num.zfill(3)


def get_uuid(manga_id):
    headers = {'Content-Type': 'application/json'}
    payload = '{"type": "manga", "ids": [' + str(manga_id) + ']}'

    resp = get_safe("https://api.mangadex.org/legacy/mapping", method=requests.post, headers=headers, data=payload)
    try:
        uuid = resp[0]["data"]["attributes"]["newId"]
    except:
        print("Please enter a valid MangaDex manga (not chapter) URL or ID.")
        sys.exit(1)
    return uuid


def get_title(uuid, lang_code):
    resp = get_safe("https://api.mangadex.org/manga/{}".format(uuid))
    try:
        title = resp["data"]["attributes"]["title"][lang_code]
    except KeyError:  # if no manga title in requested dl language
        try:
            title = resp["data"]["attributes"]["title"]["en"] if "en" in resp["data"]["attributes"]["title"] else resp["data"]["attributes"]["title"]['jp']
        except:
            print("Error - could not retrieve manga title.")
            sys.exit(1)
    return title


def dl(manga_id):
    global download_dir
    lang_code = "en"
    zip_up = True
    ds = False

    uuid = manga_id

    if manga_id.isnumeric():
        uuid = get_uuid(manga_id)
        if not uuid:
            return

    title = get_title(uuid, lang_code)
    if not title:
        return
    print("\nTITLE: {}".format(html.unescape(title)))

    # check available chapters & get images
    chap_list = []
    r = get_safe(
        "https://api.mangadex.org/manga/{}/feed?limit=0&translatedLanguage[]={}".format(uuid, lang_code))
    try:
        total = r["total"]
    except KeyError:
        print("Error retrieving the chapters list. Did you specify a valid language code?")
        sys.exit(1)

    if total == 0:
        print("No chapters available to download!")
        return

    offset = 0
    while offset < total:  # if more than 500 chapters!
        chaps = get_safe(
            "https://api.mangadex.org/manga/{}/feed?order[chapter]=asc&order[volume]=asc&limit=500&translatedLanguage[]={}&offset={}".format(uuid, lang_code, offset))
        for chapter in chaps["results"]:
            chap_num = chapter["data"]["attributes"]["chapter"]
            chap_uuid = chapter["data"]["id"]
            chap_list.append(("Oneshot", chap_uuid) if chap_num ==
                             None else (chap_num, chap_uuid))
        offset += 500
    chap_list.sort(key=float_conversion)  # sort numerically by chapter #

    # i/o for chapters to download
    requested_chapters = []

    dl_list = [str(i[0]) for i in chap_list]
    chap_list_only_nums = [i[0] for i in chap_list]
    for s in dl_list:
        if "-" in s:
            split = s.split('-')
            lower_bound = split[0]
            upper_bound = split[-1]
            try:
                lower_bound_i = chap_list_only_nums.index(lower_bound)
            except ValueError:
                print("Chapter {} does not exist. Skipping range {}.".format(
                    lower_bound, s))
                continue  # go to next iteration of loop
            try:
                upper_bound_i = chap_list_only_nums.index(upper_bound)
            except ValueError:
                print("Chapter {} does not exist. Skipping range {}.".format(
                    upper_bound, s))
                continue
            s = chap_list[lower_bound_i:upper_bound_i+1]
        elif s.lower() == "oneshot":
            if "Oneshot" in chap_list_only_nums:
                oneshot_idxs = [i for i, x in enumerate(
                    chap_list_only_nums) if x == "Oneshot"]
                s = []
                for idx in oneshot_idxs:
                    s.append(chap_list[idx])
            else:
                print("Chapter Oneshot does not exist. Skipping.")
                continue
        else:  # single number (but might be multiple chapters numbered this)
            chap_idxs = [i for i, x in enumerate(
                chap_list_only_nums) if x == s]
            if len(chap_idxs) == 0:
                print("Chapter {} does not exist. Skipping.".format(s))
                continue
            s = []
            for idx in chap_idxs:
                s.append(chap_list[idx])
        requested_chapters.extend(s)

    for chapter_info in requested_chapters:
        group_uuids = []
        for entry in chapter["relationships"]:
            if entry["type"] == "scanlation_group":
                group_uuids.append(entry["id"])

        groups = ""
        for i, group in enumerate(group_uuids):
            if i > 0:
                groups += " & "
            r = get_safe("https://api.mangadex.org/group/{}".format(group))
            name = r["data"]["attributes"]["name"]
            groups += name

        groupname = re.sub('[/<>:"/\\|?*]', '-', groups)
        groupname = groupname if groupname else "No Group"

        chapnum = zpad(chapter_info[0])
        if chapnum != "Oneshot" and chapnum.isnumeric():
            chapnum = 'c' + chapnum
        title = re.sub('[/<>:"/\\|?*]', '-', html.unescape(title))

        zip_name = os.path.join(download_dir, "download", title, "{} {} [{}]".format(
                title, chapnum, groupname)) + ".cbz"
        if os.path.isfile(zip_name):
            continue

        print("Downloading chapter {} of {}".format(chapter_info[0], html.unescape(title)))
        chapter = get_safe(
            "https://api.mangadex.org/chapter/{}".format(chapter_info[1]))
        r = get_safe(
            "https://api.mangadex.org/at-home/server/{}".format(chapter_info[1]))
        baseurl = r["baseUrl"]

        # make url list
        images = []
        accesstoken = ""
        chaphash = chapter["data"]["attributes"]["hash"]
        datamode = "dataSaver" if ds else "data"
        datamode2 = "data-saver" if ds else "data"

        for page_filename in chapter["data"]["attributes"][datamode]:
            images.append("{}/{}/{}/{}".format(baseurl,
                                               datamode2, chaphash, page_filename))

        # download images
        for pagenum, url in enumerate(images, 1):
            filename = os.path.basename(url)
            ext = os.path.splitext(filename)[1]

            dest_folder = os.path.join(
                download_dir, "download", title, "{} [{}]".format(chapnum, groupname))
            if not os.path.exists(dest_folder):
                os.makedirs(dest_folder)
            dest_filename = pad_filename("{}{}".format(pagenum, ext))
            outfile = os.path.join(dest_folder, dest_filename)

            if os.path.isfile(outfile + ".temp"):
                os.remove(outfile + ".temp")
            elif os.path.isfile(outfile):
                continue

            binary_data = get_safe_binary_data(url)

            with open(outfile + ".temp", 'wb') as f:
                f.write(binary_data)
                print(" Downloaded page {} of {} of {}".format(pagenum, chapter_info[0], html.unescape(title)))
            os.replace(outfile + ".temp", outfile)

        if zip_up:
            chap_folder = os.path.join(
                download_dir, "download", title, "{} [{}]".format(chapnum, groupname))
            with zipfile.ZipFile(zip_name, 'w') as myzip:
                for root, dirs, files in os.walk(chap_folder):
                    for file in files:
                        path = os.path.join(root, file)
                        myzip.write(path, os.path.basename(path))
            print("Chapter {} of {} successfully packaged into .cbz file.".format(chapnum, title))
            # remove original folder of loose images
            shutil.rmtree(chap_folder)
    print("Done downloading: {}".format(manga_id))


def get_limit():
    link = "https://api.mangadex.org/manga?offset=0&limit=1&status[]=completed"
    r = get_safe(link)
    return r['total']


def parse_page(link):
    r = get_safe(link)
    return [
        x['data']['id']
        for x in r['results']
    ]


def download_all_completed_manga():
    limit = get_limit()

    offsets = []

    while limit > 100:
        limit -= 100
        if offsets == []:
            offsets.append(0)
            continue
        offsets.append(100)

    if limit > 0:
        offsets.append(limit)
        limit = 0

    for offset in offsets:
        link = "https://api.mangadex.org/manga?offset={}&limit=100&status[]=completed".format(offset)
        ids = parse_page(link)
        results = ThreadPool(2).imap_unordered(dl, ids)
        for i in results:
            pass


if __name__ == "__main__":
    download_all_completed_manga()

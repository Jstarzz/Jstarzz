#!/usr/bin/env python3
"""Update GitHub profile PR counters using repositories accessible to PR_STATS_TOKEN."""

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USERNAME = "Jstarzz"
API_ROOT = "https://api.github.com"
TOKEN = os.environ.get("PR_STATS_TOKEN", "")
README_PATH = Path("README.md")

MERGED_PRS_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: MERGED, first: 100, after: $cursor) {
      nodes {
        mergedBy { login }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""


def github(path, data=None):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {TOKEN}",
        "User-Agent": "Jstarzz-profile-pr-stats",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = json.dumps(data).encode("utf-8") if data is not None else None
    request = Request(API_ROOT + path, data=body, headers=headers)
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def count_authored_and_merged():
    params = urlencode({"q": f"is:pr is:merged author:{USERNAME}", "per_page": 1})
    result = github("/search/issues?" + params)
    if result.get("incomplete_results"):
        raise RuntimeError("GitHub search returned incomplete results")
    return result["total_count"]


def writable_repositories():
    page = 1
    while True:
        params = urlencode({
            "affiliation": "owner,collaborator,organization_member",
            "per_page": 100,
            "page": page,
        })
        repositories = github("/user/repos?" + params)
        for repository in repositories:
            # Only repositories where this account could merge PRs.
            if repository.get("permissions", {}).get("push"):
                yield repository["owner"]["login"], repository["name"]
        if len(repositories) < 100:
            break
        page += 1


def count_personally_merged():
    total = 0
    for owner, name in writable_repositories():
        cursor = None
        while True:
            response = github("/graphql", {
                "query": MERGED_PRS_QUERY,
                "variables": {"owner": owner, "name": name, "cursor": cursor},
            })
            if response.get("errors"):
                raise RuntimeError("GitHub GraphQL query failed")
            repository = response["data"]["repository"]
            if repository is None:
                raise RuntimeError("Repository was not available to GraphQL")
            pulls = repository["pullRequests"]
            total += sum(
                1 for pr in pulls["nodes"]
                if pr["mergedBy"] is not None
                and pr["mergedBy"]["login"].casefold() == USERNAME.casefold()
            )
            if not pulls["pageInfo"]["hasNextPage"]:
                break
            cursor = pulls["pageInfo"]["endCursor"]
            if not cursor:
                raise RuntimeError("GitHub returned an invalid pagination cursor")
    return total


def update_readme(authored, merged):
    readme = README_PATH.read_text(encoding="utf-8")
    badges = (
        "![Merged PRs authored]"
        f"(https://img.shields.io/badge/Merged%20PRs%20Authored-{authored}-2ea44f?style=for-the-badge)\n"
        "![PRs personally merged]"
        f"(https://img.shields.io/badge/PRs%20Personally%20Merged-{merged}-0969da?style=for-the-badge)"
    )
    pattern = (
        r"(?<=<!-- PR_STATS_START -->\n)"
        r".*?"
        r"(?=\n<!-- PR_STATS_END -->)"
    )
    updated, replacements = re.subn(
        pattern, lambda _: badges, readme, flags=re.DOTALL
    )
    if replacements != 1:
        raise RuntimeError("Expected exactly one PR_STATS marker section")
    if updated != readme:
        README_PATH.write_text(updated, encoding="utf-8")


def main():
    if not TOKEN:
        raise RuntimeError("Add the PR_STATS_TOKEN Actions secret first")
    authored = count_authored_and_merged()
    merged = count_personally_merged()
    update_readme(authored, merged)
    print(f"Updated two PR counters: authored-and-merged={authored}, personally-merged={merged}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Do not disclose private repository names or response bodies in public Actions logs.
        print(f"PR stats update failed ({type(error).__name__}).", file=sys.stderr)
        sys.exit(1)

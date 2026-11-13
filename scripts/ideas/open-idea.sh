#!/usr/bin/env bash
set -eu
repo=yangliang2/excalidraw
url=$(gh issue create -R "$repo" --title "$1" --body-file "$2")
echo "$url"
number=${url##*/}
gh issue develop "$number" -R "$repo" --base master --name "idea/$number-$3"

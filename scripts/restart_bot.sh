#!/usr/bin/env bash
set -euo pipefail

sudo systemctl restart trading-bot
sudo systemctl status trading-bot --no-pager
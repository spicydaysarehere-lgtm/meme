name: Post Reddit Media

on:

  workflow_dispatch:

  schedule:

    - cron: "0 * * * *"


permissions:

  contents: write


concurrency:

  group: reddit-media-post

  cancel-in-progress: false


jobs:

  post:

    runs-on: ubuntu-latest

    steps:

      - name: Checkout repository

        uses: actions/checkout@v4

        with:

          fetch-depth: 0

          ref: main


      - name: Setup Python

        uses: actions/setup-python@v5

        with:

          python-version: "3.11"


      - name: Install FFmpeg

        run: |

          sudo apt-get update

          sudo apt-get install -y ffmpeg


      - name: Install dependencies

        run: |

          python -m pip install --upgrade pip

          python -m pip install requests


      - name: Run bot

        env:

          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}

          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}

        run: |

          python -u post_meme.py


      - name: Save posting history

        if: success()

        run: |

          git config user.name "github-actions[bot]"

          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

          git add posted.json

          if git diff --cached --quiet; then

            echo "No changes"

            exit 0

          fi

          git commit -m "Update posting history"

          git fetch origin main

          git checkout main

          git merge origin/main --no-edit || true

          git push origin main || (

            git pull origin main --no-edit

            git push origin main

          )

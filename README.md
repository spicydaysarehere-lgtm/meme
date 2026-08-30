# Telegram Meme Auto-Poster (100% Free)

Posts a fresh, non-repeating meme to your Telegram channel every 10 minutes,
forever, without needing your own server. It runs on GitHub Actions' free tier.

## How it works
- `post_meme.py` fetches a random meme from https://meme-api.com (free, no key,
  pulls from popular meme subreddits) and posts it to your channel via the
  Telegram Bot API.
- `posted.json` keeps a rolling memory of recently posted image URLs so you
  don't get the same meme twice in a row.
- `.github/workflows/post-meme.yml` tells GitHub to run the script every
  10 minutes automatically, free of charge.

## One-time setup (about 10 minutes)

### 1. Create your Telegram bot
1. Open Telegram, message **@BotFather**.
2. Send `/newbot`, follow the prompts, and give it a name + username.
3. BotFather will give you a **bot token** — looks like
   `123456789:AAExampleTokenHere`. Save it somewhere safe.

### 2. Add the bot to your channel
1. Open your channel's settings → **Administrators** → **Add Admin**.
2. Add your new bot and give it permission to **Post Messages**.

### 3. Get your channel's chat ID
- If your channel has a public username, you can just use `@yourchannelname`
  as the chat ID — no lookup needed.
- If it's private, get the numeric ID:
  1. Post any message in the channel.
  2. Visit `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` in a
     browser (replace `<YOUR_BOT_TOKEN>`).
  3. Look for `"chat":{"id": -1001234567890, ...}` in the JSON — that number
     (including the minus sign) is your chat ID.

### 4. Put this code on GitHub
1. Create a new **GitHub account** if you don't have one (free).
2. Create a new repository (can be private or public — both work, private
   repos get 2,000 free Action-minutes/month, which is more than enough for
   a run every 10 minutes).
3. Upload all the files in this folder to that repository (drag-and-drop
   works on github.com, or use `git push` if you're comfortable with git).

### 5. Add your secrets
In your new repo: **Settings → Secrets and variables → Actions → New
repository secret**, and add two secrets:
- `TELEGRAM_BOT_TOKEN` → your bot token from step 1
- `TELEGRAM_CHAT_ID` → your channel's `@username` or numeric ID from step 3

### 6. Turn it on
- Go to the **Actions** tab of your repo → you should see "Post Meme to
  Telegram" → click **Enable workflow** if prompted.
- Click **Run workflow** once to test it manually.
- Check your Telegram channel — a meme should appear within a few seconds.
- After that, it runs automatically every 10 minutes, forever, for free.

## Notes & limits
- GitHub's free cron scheduler is "best-effort" — during periods of high
  GitHub-wide load, a run might fire a few minutes late. It won't ever cost
  you money or require you to touch anything, though.
- The meme source (meme-api.com) is a free public service with no login. If
  it's ever down, the script just skips that run quietly and tries again on
  the next 10-minute cycle.
- You can freely edit the `SUBREDDITS` list inside `post_meme.py` to change
  what kind of memes get posted (line near the top of the file).
- To pause posting, just disable the workflow from the Actions tab. To go
  back to normal, re-enable it.

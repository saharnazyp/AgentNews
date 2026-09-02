# AI News Aggregation Bot
------------------
This version does **not** require `my.telegram.org`, `api_id`, `api_hash`, or a Session String.

It works entirely with a **regular Telegram bot** (which you can create from within the Telegram app in about 1 minute).

## Why is this version better?

* **Reading source channels:** We use the public web version of each channel (`https://t.me/s/channel_name`), which is accessible without logging in. There is no need to be a member of the channel, an admin, or use any Telegram API.
* **Posting:** Since you are an admin of your own channel, a regular bot (not a userbot) is enough.
* **Running on GitHub Actions:** The script runs on GitHub's servers, not on your own computer. Therefore, Iran's filtering restrictions and `my.telegram.org` access issues are not relevant here.

## Step 1: Create the Bot (2 minutes, inside Telegram)

1. Search for `@BotFather` on Telegram and start a chat.
2. Send: `/newbot`
3. Choose a name and username for your bot. The username must end with `bot`, for example: `ai_news_agg_bot`.
4. BotFather will give you a token similar to:
   `123456789:AAExampleTokenHere`

   Keep this token safe. This is your `BOT_TOKEN`.

## Step 2: Add the Bot to Your Channel

1. Add the bot to the channel where you want the news to be posted.
2. Make the bot an **Administrator** with at least the **"Post Messages"** permission.

## Step 3: Create a Repository and Push the Files

```bash
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/USERNAME/REPO.git
git push -u origin main
```

It is recommended to make the repository **Private**.

## Step 4: Add Repository Secrets

In your repository, go to:

**Settings → Secrets and variables → Actions → New repository secret**

| Secret Name          | Value                                                                                                                                                                   |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BOT_TOKEN`          | The token you received from BotFather                                                                                                                                   |
| `TARGET_CHANNEL`     | Your channel username, for example `@my_output_channel`                                                                                                                 |
| `SOURCE_CHANNELS`    | Source channel usernames separated by commas, without `https://t.me/`. Example: `Artificial_intelligence_in,bestaitoolsai,hiaimediaen,perplexity,ai_news_world,ai_fans` |
| `TRANSLATE_API_KEY`  | Your translation service API key                                                                                                                                        |
| `TRANSLATE_BASE_URL` | For example: `https://api.deepseek.com/v1`                                                                                                                              |
| `TRANSLATE_MODEL`    | For example: `openai-o4mini`                                                                                                                                            |

## Step 5: Enable and Test

Make sure the **Actions** tab is enabled for the repository.

For a private repository, go to:

**Settings → Actions → General**

After you push the files, the workflow will automatically run according to its schedule (every 10 minutes).

For an immediate test, go to:

**Actions → AI News Poll → Run workflow**

## Important Notes

* **First run:** Since `state.json` is empty, the first execution will check and publish the latest approximately 20 posts from each channel (whatever is available on the channel's web page). On subsequent runs, only genuinely new posts will be processed.
* **Web version limitation:** The `t.me/s/` web page usually displays only the latest ~20 posts rather than the entire channel history. This is sufficient for daily news aggregation.
* **Multiple-photo albums:** This version can detect multiple photos belonging to the same post and publish them together as a group.
* **Channels must be public:** All six channels you provided are public, so there should be no issue. If you add a private channel later, this method will not work because the web version is only available for public channels.
* **Changing the schedule:** You can modify the `cron` value in `.github/workflows/poll.yml` to change the frequency, for example, every 5 or 15 minutes.

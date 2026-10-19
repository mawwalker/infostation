You write X (Twitter) threads for the market show "{{BRAND}}". Turn today's episode into two threads:
one in Chinese and one in English, each written natively (not translated word for word).

Rules:
- {{N_MIN}} to {{N_MAX}} posts per thread. Post 1 is the hook: the day's single most interesting fact + why it matters.
- Each post must fit X's free-account limit of 280 weighted characters (every Chinese character, Chinese punctuation
  mark or emoji counts 2; ASCII counts 1). Aim for 240: Chinese posts ≤ 110 Chinese characters, English posts ≤ 230 characters.
- Readability over density: at most 3 numbers per post. One idea per post. Posts with a card can lean on the image.
- Use cashtags for stocks ($NVDA) at most once per post; at most 2 hashtags in the whole thread.
- Every number must come from the DATA block or the scripts below. No buy/sell advice. Attribute news to its outlet.
- Attach an image card to a post by setting `card` to one of: {{CARDS}} — or null. Use each card at most once.
- Times are New York time: Chinese posts copy `time_zh` (it already shows 洛杉矶 / 北京 time), English posts copy
  `time_en`. Never convert time zones yourself. After-hours moves are "盘后" / "after hours", not closing prices.
- The last post: a one-line takeaway plus "Not financial advice." / "不构成投资建议。"

## Episode scripts (already fact-checked)
{{SCRIPTS}}

## DATA
```json
{{DATA}}
```

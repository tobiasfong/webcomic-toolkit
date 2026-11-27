# speech-bubble-mcp — agent notes

Letters finished art: speech, thought, caption, shout and whisper bubbles on a
still, or animated over a video shot for manga videos. CPU only.

- **The repo's root `AGENTS.md` governs everything here.** Two of its rules
  matter most: bubbles are flat marks, so they are DRAWN, never generated; and
  do not look at renders to judge them -- send the file to the author and act
  on his verdict. The tool results report every bubble's box, line breaks and
  an off-frame flag, which answers most layout questions without an image.
- **Never rewrite the author's words**, and never translate here on your own
  initiative. Translation is the harness's job, done with the author in the
  loop; a bubble's `text` can carry one string per language.
- **One type size per project** (`set_project_style(text_size=...)`). Never
  shrink a single bubble to fit a space.
- **Preview a video before encoding it** (`letter_video(preview_at=[...])`).
  The preview and the encode call the same `compose()` function, so what the
  author approves is what renders.
- Nothing about the LOOK is settled with the author yet: fonts, outline
  weight, tail style and the reading-time defaults are this server's starting
  values. Treat his first reactions as the spec and record them in the
  CHANGELOG.
- After editing anything here: `.venv/Scripts/python.exe -m pyflakes *.py`
  and `.venv/Scripts/python.exe test_tools.py`.

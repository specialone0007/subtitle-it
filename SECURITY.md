# Security

Please report a security problem privately through GitHub's
[private vulnerability reporting](https://github.com/specialone0007/turkish-subtitles/security/advisories/new),
not in a public issue.

What the plugin keeps and sends:

- Your OpenSubtitles key and login, and your Hugging Face token, are typed
  into a setup command in your own terminal, never into the chat. They are
  saved in `~/.config/turkish-subtitles/credentials.json` with owner-only
  permissions where the system supports it, and only the scripts read them.
  The OpenSubtitles key and login are sent only to OpenSubtitles, to log in,
  and the Hugging Face token only to Hugging Face, to download the speaker
  models.
- The credentials file is plain text. It holds your OpenSubtitles API key,
  username and password, the login token, and your Hugging Face token,
  none of them encrypted. Anyone who can read files as your user, or a
  backup of your home folder, can read them.
- Audio hints load the pyannote model checkpoints with PyTorch's full
  pickle loading (`TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1` in
  `scripts/speakers.py`), because those checkpoints do not load in its
  weights-only mode. Full loading can run code stored in a checkpoint, so
  the plugin trusts the files from pyannote's own repositories on Hugging
  Face. A tampered checkpoint there or in your Hugging Face cache could run
  code on your machine.
- Subtitle text is sent to Claude as part of your Claude Code session.
- OpenSubtitles receives the film's hash, title or IMDb id when it searches.
- A web search receives the film's title and year: the skill looks them up
  once when it does not know them, and the bible writer and second reader
  search for the cast and plot.
- Audio hints run on your machine. They download models from Hugging Face,
  and no audio leaves your machine.
- Speech-to-text, the last resort when no subtitle file exists, runs on your
  machine too. It downloads its Whisper model from Hugging Face once, needs
  no token, and sends no audio anywhere.

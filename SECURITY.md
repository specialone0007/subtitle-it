# Security

Please report a security problem privately through GitHub's
[private vulnerability reporting](https://github.com/specialone0007/turkish-subtitles/security/advisories/new),
not in a public issue.

What the plugin keeps and sends:

- Your OpenSubtitles key and login, and your Hugging Face token, are typed
  into a setup command in your own terminal, never into the chat. They are
  saved in `~/.config/turkish-subtitles/credentials.json` with owner-only
  permissions where the system supports it, and only the scripts read them.
- Subtitle text is sent to Claude as part of your Claude Code session.
- OpenSubtitles receives the film's hash, title or IMDb id when it searches.
- Audio hints run on your machine. They download models from Hugging Face,
  and no audio leaves your machine.

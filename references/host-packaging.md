# Explicit-only host packaging

Keep one source tree. To create a new installation copy without changing the source:

```sh
python scripts/package_skill.py --host codex --output '<new-separate-directory>/batch-video-transcription'
python scripts/package_skill.py --host claude --output '<new-separate-directory>/batch-video-transcription'
```

Destinations must not exist and must be separate from the source tree. The generator copies an explicit source/document/test whitelist, not Git history or runtime data. It does not install or upload. Review the output before installation, obtain installation permission, and regenerate into a new destination after source changes.

- Codex: `agents/openai.yaml` sets `policy.allow_implicit_invocation: false`; explicitly invoke `$batch-video-transcription`. Install under the host's configured skills directory (normally `~/.codex/skills/`, or `skills` under `CODEX_HOME`).
- Claude Code: the generator adds `disable-model-invocation: true` to the generated skill frontmatter; explicitly invoke `/batch-video-transcription`. Install under `~/.claude/skills/` or project `.claude/skills/`. See https://code.claude.com/docs/en/skills .
- Do not mix the Claude field into the primary Codex package: its current validator rejects that field. Metadata generation is tested, but actual Claude loading is not verified. Other hosts need their own explicit-only policy and runtime checks; descriptive instructions alone do not enforce host selection.

Never overwrite an existing installation, expose private data, or assume a packaging request authorizes publication.

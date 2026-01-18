# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [Unreleased]

## [0.1.1] - 2026-01-17
### Added
- Click-to-add suggestions for Audience, Tags/hashtags, and Tone.
- Tooltip help markers for key fields.
- Configurable builder defaults and suggestion lists via environment variables.
- CTA validation (requires a valid @handle or URL when enabled; auto-prefixes https:// for bare domains).
- Plain-language user guide and improved README.

## [0.1.0] - 2026-01-17
### Added
- Flask + SQLite post builder with project-scoped uploads and plan history.
- Strict canonical plan schema with template mode (no AI) and explicit validation errors.
- Bluesky posting (images only) with app-password auth, link facets, and image optimization under 1MB.
- Post Builder UX polish: upload-first flow, Bluesky character counter, warm gradient background.
- Media preview modal with left/right navigation.

[Unreleased]: https://github.com/zebadrabbit/HelpMePost/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/zebadrabbit/HelpMePost/releases/tag/v0.1.1
[0.1.0]: https://github.com/zebadrabbit/HelpMePost/releases/tag/v0.1.0

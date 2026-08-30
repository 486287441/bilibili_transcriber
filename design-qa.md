# Design QA — 任务耗时明细

- Source visual truth: `D:\APP\wechatDocument\xwechat_files\wxid_93jgeb95ls5n22_7c8f\temp\RWTemp\2026-08\9e20f478899dc29eb19741386f9343c8\2582281084ec864e6d166b0e07c43663.png`
- Browser-rendered implementation: `D:\code\bilibili_transcriber\artifacts\task-timing-dialog.png`
- Combined comparison: `D:\code\bilibili_transcriber\artifacts\task-timing-comparison.png`
- State: 设置 → 运行日志 → 点击“任务已全部完成”的“查看耗时”
- Viewport: 1280 × 720 CSS px, device pixel ratio 1.5
- Source pixels: 940 × 346
- Implementation capture pixels: 1265 × 712
- Density normalization: comparison canvas vertically centers the unscaled source and browser capture. The source is an information-structure reference rather than a same-viewport visual mock, so exact pixel fidelity is intentionally not asserted.

## Full-view comparison evidence

The source calls for a total duration, a slowest-stage summary, and individually readable phase durations. The implementation contains all three while preserving the app's parchment, ink-blue, serif-led visual system. The secondary dialog is visually subordinate to the existing settings dialog and does not increase timeline density.

## Focused-region comparison evidence

The summary card and phase list were checked at readable browser scale. Total duration, slowest-stage emphasis, phase labels, seconds, percentages, and proportional bars are legible. A focused check was necessary because the reference's value lies in timing hierarchy and phase granularity rather than overall page composition.

## Findings

- No remaining P0/P1/P2 issues.
- Fonts and typography: buttons now use the same TsangerJinKai02-led serif stack as the page; hierarchy and numeric emphasis are consistent.
- Spacing and layout rhythm: dialog padding, summary split, row spacing, borders, and scrollbar behavior fit the existing settings surface.
- Colors and visual tokens: only existing parchment, ink-blue, border, and semantic tokens are used; contrast and modal layering are clear.
- Image quality and assets: no raster assets or custom icon approximations are needed in this data-only dialog.
- Copy and content: the final log exposes “查看耗时”; the dialog separates B 站字幕检查、媒体下载、语音识别模型加载、语音转写、文章校对与润色、飞书发布。

## Comparison history

1. P2 — The first implementation combined model loading with transcription and omitted subtitle-check time. Fixed by adding task-specific `subtitle_sec` and `model_load_sec` measurements and rendering them as independent stages. Post-fix browser evidence shows six distinct phases.
2. P2 — History action buttons used a different Chinese font from global controls. Fixed by unifying the global button family with the page serif stack. Browser-computed styles confirm 设置、搜索、查看结果、追问、删除 use the same family.
3. P2 — 删除 used a red text treatment while the requested design called for parity with 追问. Fixed by applying the same `history-action ghost` treatment. Browser evidence confirms matching classes and styling.

## Primary interactions tested

- Open settings and switch among API 配置、Prompt 调整、运行日志.
- Open the timing dialog from the final completion event.
- Close the timing dialog and return to the settings dialog.
- Close settings and verify history action rendering.
- Confirm keyboard-focusable buttons and descriptive timing-entry label.
- Check browser console; the earlier preview-port CORS error was resolved by using the configured local development origin, with no new final-state errors observed.

## Follow-up polish

- P3: very short stages round to 0% while retaining their exact seconds and a minimum visible bar. This is acceptable and avoids overstating their share.

final result: passed

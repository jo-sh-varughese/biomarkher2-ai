# BioMarkHER2 AI — User Guide

*A plain-language guide for a pathologist using this tool for the first
time. If you're setting up or developing the viewer instead, see
`app/README.md`.*

## Purpose

BioMarkHER2 AI is a pre-scoring assistant for reviewing HER2 IHC tissue images.

It helps the pathologist by showing:

- The original image
- The detected tissue region
- Model-based staining regions
- A classical baseline comparison
- Percentage measurements for the detected tissue
- Areas where the model and baseline disagree

The tool does **not** assign a HER2 score or diagnosis.

## Basic workflow

1. Open the BioMarkHER2 AI viewer.
2. Upload the HER2 IHC image or select an available sample.
3. Wait for the analysis to complete.
4. Review the original image and tissue mask.
5. Review the model and baseline results.
6. Compare the percentage measurements.
7. Pay attention to the displayed caveats and limitations.
8. Complete the required pathologist review.
9. Record the review decision.

## Understanding the results

### Original

Shows the image supplied for analysis.

### Tissue

Shows the tissue region used for the measurements.

### Model

Shows the staining classes predicted by the segmentation model.

### Baseline

Shows the result from the classical image-processing baseline.

### Percentages

Percentages are calculated over the detected tissue region rather than the background.

The model and baseline use the same tissue region so that their measurements can be compared.

## Important limitation

The moderate (2+) class is not reliable enough for independent interpretation.

The current model cannot reliably distinguish moderate (2+) staining from the surrounding staining patterns. FISH testing may therefore be required when clinically appropriate.

## Pathologist review

The tool is intended to assist, not replace, pathologist review.

The review step must be completed explicitly after examining the results.

The system should not be used as an autonomous diagnostic tool.

## Reports

A PDF report can be generated from the analysis results.

Review the report for:

- Original image
- Tissue information
- Model results
- Baseline comparison
- Important caveats
- Pathologist review information

The report is intended to support review and documentation.

### Printing the report

The report is designed to still make sense if printed or photocopied in
black-and-white. The intensity images use a colour scale that gets steadily
darker as staining gets stronger, so the order (negative → weak → moderate →
strong) survives greyscale printing. The percentage table and the moderate
(2+) limitation notice are printed as ordinary text, not colour-coded, so
they read the same on paper as on screen.

## Important reminder

BioMarkHER2 AI is a research and pre-scoring tool.

It is **not validated for diagnostic use** and does not independently provide a HER2 diagnosis.

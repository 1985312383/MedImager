# MedImager icon system

Runtime icons are project-authored SVGs on a 24 x 24 grid. They use a 2 px
round stroke and `currentColor`; `IconRegistry` supplies semantic colors for
normal, active, selected and disabled Qt icon modes. No icon-font or external
runtime package is required.

The `legacy` directory contains unreferenced historical bitmap controls and is
intentionally excluded from package data.

# Deterministic headless demo traces

Run `python3 -m demos.run_demos` to print the complete JSON traces, including
all ten ranked ASINs and the evaluator-verified target rank. The Agent never sees
the target; only this demo verifier reads the public label after each response.

## 1. Buying — `public_0149`

1. Customer asks for a casual daypack/backpack with a hard leather requirement.
   The agent returns ten valid products and asks for brand.
2. Customer has no additional brand preference. Candidate rotation produces a
   new shortlist and finds `B07CBYYHTL` at rank 2.

## 2. Browsing — `public_0006`

1. Customer is still exploring basketball products. The agent provides a
   diverse shortlist and asks the structured composite `other` clarification.
2. Customer reveals polyester constraints. The accumulated query finds
   `B071F2Z7JG` at rank 1.

## 3. Intent override — `public_0072`

1. Customer begins with a women's anorak category and an old department/style
   preference. The agent asks a composite clarification.
2. Customer reveals faux-fur and drawstring preferences; no hit is scored before
   the official override.
3. Customer says to ignore the earlier preference and prioritizes faux fur. The
   state generation advances, old non-category evidence/exclusions are cleared,
   and `B09JG4V9ZR` is rank 1.

## 4. Boundary — `public_0131`

1. Customer is exploring leg warmers. The agent gives a diverse shortlist and
   asks `other`.
2. Customer explicitly has no preference for that attribute. The tombstone
   prevents repeating it, candidate rotation continues, and `B07PQQQ8ZL` is
   rank 2.

These public examples are demonstration evidence only and are not read or
special-cased by `agent.py` or `shopping_copilot/`.

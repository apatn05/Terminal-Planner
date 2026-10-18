"""
Run this to see how well the model learned and what rules it found:
    python train_model.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

from sklearn.model_selection import cross_val_score
from sklearn.tree import DecisionTreeClassifier, export_text

from model import FEATURES, ROWS, row_to_features

X = [row_to_features(r) for r in ROWS]
y = [r["Recommended Action"] for r in ROWS]

# Honest accuracy: train on 4/5 of the data, test on the 1/5 it hasn't seen, 5 times.
tree = DecisionTreeClassifier(max_depth=5, random_state=0)
scores = cross_val_score(tree, X, y, cv=5)
print(f"Accuracy on unseen rows: {scores.mean():.0%} (5-fold cross-validation)\n")

tree.fit(X, y)
print("Rules the tree learned:")
print(export_text(tree, feature_names=FEATURES))

"""Optional: chemical structure image -> SMILES with DECIMER, validated by RDKit.
Install separately (heavy, TensorFlow): pip install decimer rdkit
Best run on Colab/Kaggle GPU. Output is a *suggestion*; always spot-check."""
from pathlib import Path
from typing import Optional


def image_to_smiles(image_path: Path) -> Optional[str]:
    try:
        from DECIMER import predict_SMILES
        from rdkit import Chem
    except ImportError:
        print("DECIMER/RDKit not installed; skipping structure recognition")
        return None
    try:
        smiles = predict_SMILES(str(image_path))
    except Exception:  # noqa: BLE001
        return None
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    return Chem.MolToSmiles(mol) if mol is not None else None

# ShapeAsPoints adapter contract

This adapter is a `docker-only` contract for optimization-based reconstruction.

## Input
- `--input`: single `.obj` (preferred), `.ply`, `.xyz`, `.txt`, `.npy`
- `.xyz/.txt/.npy` are converted to `.ply` with estimated normals before `optim.py`

## Output
- Returns one reconstructed mesh: `<input_stem>_sap_mesh.ply`
- Temporary optimization artifacts are stored under `<output_dir>/<input_stem>_sap_run/`

## Runtime params
- `--repo-path`: local repo path (default `external_models/ShapeAsPoints`)
- `--config`: config relative to repo (default `configs/optim_based/teaser.yaml`)
- `--total-epochs`: optimization iterations (default `200`)
- `--grid-res`: poisson grid resolution (default `128`)
- `--no-cuda`: force CPU mode

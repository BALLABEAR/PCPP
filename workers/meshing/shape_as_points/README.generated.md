# Generated adapter notes

- entry-command (source): `python -c "import pathlib,glob,shutil,subprocess; import open3d as o3d; from workers.base.format_converter import FormatConverter; run_dir=pathlib.Path('{output_dir}')/'sap_run'; run_dir.mkdir(parents=True,exist_ok=True); conv=FormatConverter(); inp_norm=conv.normalize(pathlib.Path('{input}'), pathlib.Path('{output_dir}')/'_norm_input'); pcd=o3d.io.read_point_cloud(str(inp_norm)); pcd.estimate_normals(); pcd.orient_normals_consistent_tangent_plane(30); inp_with_norm=pathlib.Path('{output_dir}')/'_input_with_normals.ply'; o3d.io.write_point_cloud(str(inp_with_norm), pcd); cmd=['python','optim.py','{config_path}','--data:data_path',str(inp_with_norm),'--train:out_dir',str(run_dir),'--train:total_epochs','300','--model:grid_res','128','--train:o3d_show','False','--data:object_id','-1','--train:n_workers','0']; subprocess.run(cmd,cwd='{repo_path}',check=True); meshes=sorted(glob.glob(str(run_dir/'vis'/'mesh'/'*.ply'))); shutil.copy(meshes[-1], str(pathlib.Path('{output_dir}')/'shape_as_points_mesh.ply'))"`
- repo-path: `./external_models/ShapeAsPoints`

Next steps:
1. Verify entry_command placeholders and repo paths
2. Fill runtime.manifest.yaml with exact deps/build steps
3. Validate with onboarding build/smoke flow

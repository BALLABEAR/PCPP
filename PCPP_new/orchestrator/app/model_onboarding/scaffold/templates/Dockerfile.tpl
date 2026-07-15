FROM {{base_image}}

{{system_packages_block}}

WORKDIR /workspace
COPY . /workspace

{{pip_install_block}}
{{env_block}}

WORKDIR /workspace/{{repo_path}}
{{build_steps_block}}
WORKDIR /workspace

CMD ["python", "/workspace/workers/{{task_type}}/{{model_id}}/worker.py"]

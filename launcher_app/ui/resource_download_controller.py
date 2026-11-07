"""Resource download interaction; jobs own network/files, this adapter owns choices."""
from launcher_app.resources.download_jobs import ResourceDownloadJob, PackDownloadJob
from launcher_app.ui.task_center import task_choice


class ResourceDownloadController:
    def __init__(self, *, parent, submit, show_status, game_root):
        self.parent = parent
        self.submit = submit
        self.show_status = show_status
        self.game_root = game_root

    def download(self, hit, version, instance, target_dir, sub_dir):
        if not target_dir:
            self.show_status('未选择安装位置')
            return
        if hit.get('source') == 'curseforge' and (not isinstance(version, dict) or not version.get('file_id')):
            self.show_status('请先在详情中选择一个 CurseForge 文件版本')
            return
        job = ResourceDownloadJob(hit, version, instance, target_dir, sub_dir)
        review = job.dependency_review()
        dependencies, skipped = (), False
        if review.missing or review.optional or review.incompatible:
            lines = [hit.get('title', hit['slug']) + ' 的依赖提示:']
            if review.missing:
                lines.append('缺少的必需前置:\n' + '\n'.join(f" · {dep['title']}" for dep in review.missing))
            if review.optional:
                lines.append('可选(选装):\n' + '\n'.join(f" · {dep['title']}" for dep in review.optional))
            if review.incompatible:
                lines.append('⚠ 冲突(不建议同装):\n' + '\n'.join(f" · {dep['title']}" for dep in review.incompatible))
            choices = [('下载并安装前置' if review.missing else '继续下载', 'install')]
            if review.missing:
                choices.append(('跳过前置，继续下载', 'skip'))
            choices.append(('取消', None))
            note = '跳过必需前置后，Mod 可能无法加载。' if review.missing else '是否继续下载该 Mod？'
            selected = task_choice(self.parent, '依赖提示', '\n'.join(lines) + '\n\n' + note, choices)
            if selected == 'install':
                dependencies = review.missing
            elif selected == 'skip':
                skipped = True
            else:
                return
        self.submit(lambda status, progress: job.run(
            status, progress, dependencies=dependencies, skipped_dependencies=skipped))

    def download_pack(self, hit, version):
        job = PackDownloadJob(hit, version, self.game_root())
        self.submit(job.run)

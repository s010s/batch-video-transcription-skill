"""Explicit, local native directory selection; never accepts executable input from HTTP."""
import subprocess,sys
from pathlib import Path

# Kept fixed: user-selected paths are returned as data, never interpolated into code.
MAC_SCRIPT='POSIX path of (choose folder with prompt "Choose the folder containing your videos")'
WINDOWS_SCRIPT=r'''Add-Type -AssemblyName System.Windows.Forms
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = 'Choose the folder containing your videos'
$d.ShowNewFolderButton = $false
if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
 [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
 [Console]::Write($d.SelectedPath)
}
$d.Dispose()
'''

def choose_directory(platform=None):
    platform=platform or sys.platform
    if platform=='darwin':command=['/usr/bin/osascript','-e',MAC_SCRIPT]
    elif platform=='win32':command=['powershell.exe','-NoProfile','-STA','-Command',WINDOWS_SCRIPT]
    else:raise ValueError('此平台暂无原生目录选择器，请展开手动输入路径；不会自动安装组件。')
    try:result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=180,check=False)
    except subprocess.TimeoutExpired:raise ValueError('目录选择超时，未创建批次；请重试或手动输入路径。') from None
    except OSError:raise ValueError('系统目录选择器不可用，请手动输入路径；未安装任何组件。') from None
    if result.returncode:
        if platform=='darwin' and '(-128)' in result.stderr:return None
        raise ValueError('系统未允许打开目录选择器；请手动输入路径，或在系统中完成必要许可。')
    value=result.stdout.strip()
    if not value:return None
    path=Path(value).expanduser().resolve(strict=True)
    if not path.is_dir():raise ValueError('选择的路径不是文件夹')
    return path

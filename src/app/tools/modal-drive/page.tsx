import type { Metadata } from "next"

import { ModalDrive } from "@/components/toolbox/modal-drive"
import { ToolShell } from "@/components/toolbox/tool-shell"

export const metadata: Metadata = {
  title: "Modal 网盘",
  description: "使用 Modal Volume 管理、上传和下载个人文件。",
}

export default function ModalDrivePage() {
  return (
    <ToolShell footerLabel="MODAL DRIVE · PYTHON + VOLUME">
      <ModalDrive />
    </ToolShell>
  )
}

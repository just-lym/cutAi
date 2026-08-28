import { ChangeEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileUp } from 'lucide-react'
import { api, type Asset } from '../api/client'

type Props = {
  projectId: string
  assets: Asset[]
}

export function AssetPanel({ projectId, assets }: Props) {
  const queryClient = useQueryClient()
  const upload = useMutation({
    mutationFn: (file: File) => api.assets.upload(projectId, file),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['timeline', projectId] })
    }
  })

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) upload.mutate(file)
  }

  return (
    <aside className="panel asset-panel">
      <div className="panel-title">
        <h2>素材</h2>
        <label className="icon-button">
          <FileUp size={17} />
          <input type="file" hidden onChange={onFile} />
        </label>
      </div>
      <div className="upload-zone">
        <FileUp size={22} />
        <span>{upload.isPending ? '上传处理中' : '选择视频、音频、图片或 SRT'}</span>
      </div>
      <div className="asset-list">
        {assets.map((asset) => (
          <div className="asset-row" key={asset.id}>
            <span>{asset.original_name}</span>
            <small data-status={asset.processing_status}>{asset.processing_status}</small>
          </div>
        ))}
      </div>
    </aside>
  )
}

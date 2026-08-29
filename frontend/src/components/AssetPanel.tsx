import { ChangeEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileAudio, FileText, FileUp, Image, RotateCw, Trash2, Video } from 'lucide-react'
import { api, type Asset } from '../api/client'
import { useEditorStore } from '../stores/editor'

type Props = {
  projectId: string
  assets: Asset[]
}

export function AssetPanel({ projectId, assets }: Props) {
  const queryClient = useQueryClient()
  const selectedAssetId = useEditorStore((state) => state.selectedAssetId)
  const selectAsset = useEditorStore((state) => state.selectAsset)
  const upload = useMutation({
    mutationFn: (file: File) => api.assets.upload(projectId, file),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['timeline', projectId] })
    }
  })

  const reprocess = useMutation({
    mutationFn: (assetId: string) => api.assets.reprocess(assetId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['timeline', projectId] })
    }
  })

  const remove = useMutation({
    mutationFn: (assetId: string) => api.assets.remove(assetId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['assets', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['timeline', projectId] })
    }
  })

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) upload.mutate(file)
    event.target.value = ''
  }

  const onRemove = (asset: Asset) => {
    if (window.confirm(`删除素材 ${asset.original_name}？`)) {
      remove.mutate(asset.id)
    }
  }

  const mediaAssets = assets.filter((asset) => ['VIDEO', 'AUDIO', 'IMAGE'].includes(asset.type))
  const subtitleAssets = assets.filter((asset) => ['SUBTITLE', 'TRANSCRIPT'].includes(asset.type))

  const iconFor = (asset: Asset) => {
    if (asset.type === 'VIDEO') return <Video size={15} />
    if (asset.type === 'AUDIO') return <FileAudio size={15} />
    if (asset.type === 'IMAGE') return <Image size={15} />
    return <FileText size={15} />
  }

  const duration = (asset: Asset) => {
    if (!asset.duration_ms) return ''
    return `${(asset.duration_ms / 1000).toFixed(1)}s`
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
      <div className="asset-library-tabs">
        <button className="active">媒体</button>
        <button>字幕</button>
      </div>
      <div className="asset-list">
        {[...mediaAssets, ...subtitleAssets].map((asset) => (
          <div
            className={selectedAssetId === asset.id ? 'asset-row selected' : 'asset-row'}
            key={asset.id}
            title={asset.processing_error ?? undefined}
            onClick={() => selectAsset(asset.id)}
          >
            <div className="asset-main">
              <span className="asset-kind">{iconFor(asset)}</span>
              <span>{asset.original_name}</span>
              <small>{asset.type}{duration(asset) ? ` · ${duration(asset)}` : ''}</small>
            </div>
            <div className="asset-actions">
              <small data-status={asset.processing_status}>{asset.processing_status}</small>
              {asset.processing_status === 'FAILED' ? (
                <button
                  className="mini-button"
                  onClick={(event) => {
                    event.stopPropagation()
                    reprocess.mutate(asset.id)
                  }}
                  disabled={reprocess.isPending}
                  title="重新处理"
                >
                  <RotateCw size={13} />
                </button>
              ) : null}
              <button
                className="mini-button danger-button"
                onClick={(event) => {
                  event.stopPropagation()
                  onRemove(asset)
                }}
                disabled={remove.isPending}
                title="删除素材"
              >
                <Trash2 size={13} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}

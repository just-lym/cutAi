import { Clapperboard, MessageSquareText, Mic2, type LucideIcon } from 'lucide-react'

export type VideoType = 'VLOG' | 'TALKING_HEAD' | 'INTERVIEW'

export type VideoModeOption = {
  value: VideoType
  label: string
  director: string
  Icon: LucideIcon
}

export const VIDEO_MODE_OPTIONS: VideoModeOption[] = [
  { value: 'VLOG', label: 'Vlog', director: 'Vlog 导演', Icon: Clapperboard },
  { value: 'TALKING_HEAD', label: '口播', director: '口播导演', Icon: Mic2 },
  { value: 'INTERVIEW', label: '访谈', director: '访谈导演', Icon: MessageSquareText }
]

export function getVideoMode(videoType: VideoType) {
  return VIDEO_MODE_OPTIONS.find((option) => option.value === videoType) ?? VIDEO_MODE_OPTIONS[1]
}

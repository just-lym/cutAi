import { Clapperboard, MessageSquareText, Mic2, type LucideIcon } from 'lucide-react'

export type VideoType = 'VLOG' | 'TALKING_HEAD' | 'INTERVIEW'

export type VideoModeOption = {
  value: VideoType
  label: string
  director: string
  description: string
  Icon: LucideIcon
}

export const VIDEO_MODE_OPTIONS: VideoModeOption[] = [
  {
    value: 'VLOG',
    label: 'Vlog',
    director: 'Vlog 导演',
    description: '旅行、日常与事件记录，侧重故事和镜头节奏',
    Icon: Clapperboard
  },
  {
    value: 'TALKING_HEAD',
    label: '口播',
    director: '口播导演',
    description: '单人讲解与观点表达，侧重语义精剪和停顿',
    Icon: Mic2
  },
  {
    value: 'INTERVIEW',
    label: '访谈',
    director: '访谈导演',
    description: '多人问答与播客，侧重上下文和说话人关系',
    Icon: MessageSquareText
  }
]

export function getVideoMode(videoType: VideoType) {
  return VIDEO_MODE_OPTIONS.find((option) => option.value === videoType) ?? VIDEO_MODE_OPTIONS[1]
}

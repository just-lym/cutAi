import { create } from 'zustand'
import type { SubtitleCue } from '../api/client'

type UndoEntry = {
  type: string
  forward: unknown
  backward: unknown
  timestamp: number
}

type EditorState = {
  playheadMs: number
  zoom: number
  isPlaying: boolean
  selectedClipIds: string[]
  draftOperations: object[]
  subtitleCues: SubtitleCue[]
  currentCueId: string | null
  selectedCueIds: string[]
  activeBottomTab: 'timeline' | 'script'
  highlightRange: { start_ms: number; end_ms: number } | null
  undoStack: UndoEntry[]
  redoStack: UndoEntry[]
  setPlayhead: (value: number) => void
  setZoom: (value: number) => void
  togglePlay: () => void
  setPlaying: (value: boolean) => void
  setSubtitleCues: (cues: SubtitleCue[]) => void
  setCurrentCue: (id: string | null) => void
  selectCue: (id: string, additive?: boolean) => void
  setBottomTab: (tab: 'timeline' | 'script') => void
  setHighlightRange: (range: { start_ms: number; end_ms: number } | null) => void
  addDraftOp: (operation: object) => void
  clearDraft: () => void
  pushUndo: (entry: UndoEntry) => void
  undo: () => void
  redo: () => void
}

export const useEditorStore = create<EditorState>((set, get) => ({
  playheadMs: 0,
  zoom: 1,
  isPlaying: false,
  selectedClipIds: [],
  draftOperations: [],
  subtitleCues: [],
  currentCueId: null,
  selectedCueIds: [],
  activeBottomTab: 'timeline',
  highlightRange: null,
  undoStack: [],
  redoStack: [],
  setPlayhead: (value) => set({ playheadMs: Math.max(0, value) }),
  setZoom: (value) => set({ zoom: Math.min(4, Math.max(0.25, value)) }),
  togglePlay: () => set((state) => ({ isPlaying: !state.isPlaying })),
  setPlaying: (value) => set({ isPlaying: value }),
  setSubtitleCues: (cues) => set({ subtitleCues: cues }),
  setCurrentCue: (id) => set({ currentCueId: id }),
  selectCue: (id, additive) =>
    set((state) => ({
      selectedCueIds: additive
        ? state.selectedCueIds.includes(id)
          ? state.selectedCueIds.filter((item) => item !== id)
          : [...state.selectedCueIds, id]
        : [id]
    })),
  setBottomTab: (tab) => set({ activeBottomTab: tab }),
  setHighlightRange: (range) => set({ highlightRange: range }),
  addDraftOp: (operation) => set((state) => ({ draftOperations: [...state.draftOperations, operation] })),
  clearDraft: () => set({ draftOperations: [] }),
  pushUndo: (entry) =>
    set((state) => ({
      undoStack: [...state.undoStack, entry].slice(-50),
      redoStack: []
    })),
  undo: () => {
    const { undoStack, redoStack } = get()
    const entry = undoStack[undoStack.length - 1]
    if (!entry) return
    set({ undoStack: undoStack.slice(0, -1), redoStack: [...redoStack, entry] })
  },
  redo: () => {
    const { undoStack, redoStack } = get()
    const entry = redoStack[redoStack.length - 1]
    if (!entry) return
    set({ redoStack: redoStack.slice(0, -1), undoStack: [...undoStack, entry] })
  }
}))

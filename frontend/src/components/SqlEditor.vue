<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { EditorState } from '@codemirror/state'
import { EditorView, keymap, lineNumbers } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
import { sql } from '@codemirror/lang-sql'
import { syntaxHighlighting, defaultHighlightStyle } from '@codemirror/language'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '输入 SELECT 查询语句…' },
  minHeight: { type: String, default: '220px' },
})

const emit = defineEmits(['update:modelValue', 'execute'])

const containerRef = ref(null)
let editorView = null

function createEditor() {
  if (!containerRef.value) return

  editorView = new EditorView({
    state: EditorState.create({
      doc: props.modelValue,
      extensions: [
        lineNumbers(),
        history(),
        sql(),
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        keymap.of([
          ...defaultKeymap,
          ...historyKeymap,
          {
            key: 'Ctrl-Enter',
            mac: 'Cmd-Enter',
            run: () => {
              emit('execute')
              return true
            },
          },
        ]),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            emit('update:modelValue', update.state.doc.toString())
          }
        }),
        EditorView.theme({
          '&': {
            fontSize: '14px',
            minHeight: props.minHeight,
          },
          '.cm-scroller': {
            fontFamily: 'Consolas, "Courier New", monospace',
            minHeight: props.minHeight,
          },
          '.cm-content': {
            minHeight: props.minHeight,
          },
          '&.cm-focused': {
            outline: 'none',
          },
        }),
        EditorView.contentAttributes.of({
          'aria-label': props.placeholder,
        }),
      ],
    }),
    parent: containerRef.value,
  })
}

function setDoc(value) {
  if (!editorView) return
  const current = editorView.state.doc.toString()
  if (current === value) return
  editorView.dispatch({
    changes: { from: 0, to: editorView.state.doc.length, insert: value ?? '' },
  })
}

function focus() {
  editorView?.focus()
}

watch(
  () => props.modelValue,
  (value) => setDoc(value),
)

onMounted(createEditor)

onUnmounted(() => {
  editorView?.destroy()
  editorView = null
})

defineExpose({ focus, setDoc })
</script>

<template>
  <div class="sql-editor">
    <div ref="containerRef" class="sql-editor-host" />
  </div>
</template>

<style scoped>
.sql-editor {
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  overflow: hidden;
  background: #fafafa;
}

.sql-editor-host :deep(.cm-editor) {
  background: #fafafa;
}

.sql-editor-host :deep(.cm-gutters) {
  background: #f0f2f5;
  border-right: 1px solid #e4e7ed;
}
</style>

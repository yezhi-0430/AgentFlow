import { defineStore } from 'pinia'
import { ref } from 'vue'
import websocket from '../services/websocket.js'
import { messageService } from '../services/workflow.js'

export const useMessageStore = defineStore('messages', () => {
  const messages = ref([])
  const selectedMessageId = ref(null)
  const isConnected = ref(false)
  const currentWorkflowId = ref(null)

  function addMessage(message) {
    // 确保消息有唯一 ID
    if (!message.id) {
      message.id = `msg_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
    }

    // 添加时间戳
    if (!message.timestamp) {
      message.timestamp = new Date().toISOString()
    }

    messages.value.push(message)
  }

  function clearMessages() {
    messages.value = []
  }

  function selectMessage(id) {
    selectedMessageId.value = id
  }

  async function loadMessages(workflowId) {
    try {
      const data = await messageService.getMessages(workflowId)
      messages.value = data.messages || []
      return data.messages
    } catch (error) {
      console.error('Failed to load messages:', error)
      return []
    }
  }

  function connectToWorkflow(workflowId) {
    if (!workflowId) return

    currentWorkflowId.value = workflowId

    // 连接 WebSocket
    websocket.connect()

    // 订阅工作流消息事件
    websocket.subscribeToWorkflow(workflowId, 'message_sent', (data) => {
      addMessage({
        id: data.id,
        sender: data.sender || data.from,
        receiver: data.receiver || data.to,
        content: data.content || data.message,
        timestamp: data.timestamp || new Date().toISOString(),
        type: data.type || 'message',
      })
    })

    // 订阅 agent 事件
    websocket.on('agent:message_sent', (data) => {
      if (data.workflow_id === workflowId) {
        addMessage({
          id: data.id || `agent_msg_${Date.now()}`,
          sender: data.agent_name,
          receiver: data.target || 'System',
          content: data.message || data.content,
          timestamp: data.timestamp || new Date().toISOString(),
          type: 'agent_message',
        })
      }
    })

    // 订阅通用消息事件
    websocket.on('message', (data) => {
      if (data.workflow_id === workflowId) {
        addMessage({
          id: data.id || `msg_${Date.now()}`,
          sender: data.from || data.sender || 'System',
          receiver: data.to || data.receiver || 'All',
          content: data.message || data.content,
          timestamp: data.timestamp || new Date().toISOString(),
          type: data.type || 'message',
        })
      }
    })

    // 连接状态监听
    websocket.on('connected', () => {
      isConnected.value = true
      console.log('MessageStore: WebSocket connected')
    })

    websocket.on('disconnected', () => {
      isConnected.value = false
      console.log('MessageStore: WebSocket disconnected')
    })

    // 加载历史消息
    loadMessages(workflowId)
  }

  function disconnectFromWorkflow() {
    if (currentWorkflowId.value) {
      // 取消订阅
      websocket.off('agent:message_sent')
      websocket.off('message')

      currentWorkflowId.value = null
    }
  }

  return {
    messages,
    selectedMessageId,
    isConnected,
    currentWorkflowId,
    addMessage,
    clearMessages,
    selectMessage,
    loadMessages,
    connectToWorkflow,
    disconnectFromWorkflow,
  }
})

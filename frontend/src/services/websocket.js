class WebSocketService {
  constructor() {
    this.socket = null
    this.listeners = new Map()
    this.isConnected = false
  }

  connect(url = null) {
    // 使用环境变量或默认值
    const wsUrl = url || import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

    if (this.socket?.connected) {
      return this.socket
    }

    // 使用原生 WebSocket 而不是 socket.io（因为后端使用 FastAPI WebSocket）
    const wsProtocol = wsUrl.startsWith('https') ? 'wss' : 'ws'
    const wsBaseUrl = wsUrl.replace(/^https?:\/\//, '')

    try {
      // 全局 WebSocket 连接
      this.ws = new WebSocket(`${wsProtocol}://${wsBaseUrl}/ws`)

      this.ws.onopen = () => {
        console.log('✅ WebSocket connected')
        this.isConnected = true
        this.emit('connected', {})
      }

      this.ws.onclose = () => {
        console.log('❌ WebSocket disconnected')
        this.isConnected = false
        this.emit('disconnected', {})

        // 5秒后尝试重连
        setTimeout(() => {
          if (!this.isConnected) {
            console.log('🔄 Attempting to reconnect...')
            this.connect(url)
          }
        }, 5000)
      }

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error)
        this.emit('error', error)
      }

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          this.handleMessage(data)
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error)
        }
      }

      return this.ws
    } catch (error) {
      console.error('Failed to connect WebSocket:', error)
      return null
    }
  }

  connectToWorkflow(workflowId, url = null) {
    const wsUrl = url || import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
    const wsProtocol = wsUrl.startsWith('https') ? 'wss' : 'ws'
    const wsBaseUrl = wsUrl.replace(/^https?:\/\//, '')

    try {
      const workflowWs = new WebSocket(`${wsProtocol}://${wsBaseUrl}/ws/${workflowId}`)

      workflowWs.onopen = () => {
        console.log(`✅ Connected to workflow ${workflowId}`)
      }

      workflowWs.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          this.handleMessage(data)
        } catch (error) {
          console.error('Failed to parse message:', error)
        }
      }

      return workflowWs
    } catch (error) {
      console.error('Failed to connect to workflow:', error)
      return null
    }
  }

  disconnect() {
    if (this.ws) {
      this.ws.close()
      this.ws = null
      this.isConnected = false
    }
  }

  handleMessage(data) {
    const { type, event, workflow_id, agent_name } = data

    // 触发对应的事件监听器
    if (type === 'workflow_event') {
      this.emit(`workflow:${workflow_id}:${event}`, data.data)
      this.emit(`workflow:${event}`, { workflow_id, ...data.data })
    } else if (type === 'agent_event') {
      this.emit(`agent:${agent_name}:${event}`, data.data)
      this.emit(`agent:${event}`, { agent_name, workflow_id, ...data.data })
    } else if (type === 'message_event') {
      this.emit(`message:${workflow_id}`, data.data)
      this.emit('message', { workflow_id, ...data.data })
    } else {
      this.emit(type, data)
    }
  }

  on(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, [])
    }
    this.listeners.get(event).push(callback)
  }

  off(event, callback) {
    if (!this.listeners.has(event)) return

    if (callback) {
      const callbacks = this.listeners.get(event)
      const index = callbacks.indexOf(callback)
      if (index > -1) {
        callbacks.splice(index, 1)
      }
    } else {
      this.listeners.delete(event)
    }
  }

  emit(event, data) {
    if (!this.listeners.has(event)) return

    const callbacks = this.listeners.get(event)
    callbacks.forEach((callback) => {
      try {
        callback(data)
      } catch (error) {
        console.error(`Error in event handler for ${event}:`, error)
      }
    })
  }

  send(data) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.error('WebSocket is not connected')
      return false
    }

    try {
      this.ws.send(JSON.stringify(data))
      return true
    } catch (error) {
      console.error('Failed to send message:', error)
      return false
    }
  }

  // 订阅工作流事件
  subscribeToWorkflow(workflowId, event, callback) {
    this.on(`workflow:${workflowId}:${event}`, callback)
  }

  unsubscribeFromWorkflow(workflowId, event, callback) {
    this.off(`workflow:${workflowId}:${event}`, callback)
  }

  // 订阅 agent 事件
  subscribeToAgent(agentName, event, callback) {
    this.on(`agent:${agentName}:${event}`, callback)
  }

  unsubscribeFromAgent(agentName, event, callback) {
    this.off(`agent:${agentName}:${event}`, callback)
  }
}

export default new WebSocketService()

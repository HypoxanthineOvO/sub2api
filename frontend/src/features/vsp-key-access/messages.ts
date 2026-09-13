export const messages = {
  zh: {
    title: '使用 API Key', base: '复制 BaseURL', key: '复制 APIKey', both: '复制 BaseURL + APIKey',
    clients: '客户端配置', back: '返回通用复制', copy: '复制配置', docs: '官方说明',
    intro: '将片段合并到用户级配置，保留已有设置。配置含密钥，请勿提交到 Git 或公开分享。',
    defaultLocation: '默认配置位置', copyPath: '复制默认路径', discouraged: '不推荐',
    locationHint: '以下均为客户端默认位置，~ 和 %USERPROFILE% 表示你自己的用户主目录。本站不会读取你的本机文件或探测自定义目录；改过位置请自行查找。文件不存在时可自行创建，已有文件请合并，勿整份覆盖。',
    discouragedHint: '本站不推荐使用此客户端；仍提供默认配置，供你自行选择。',
    zcodeHint: '默认文件位置仅供定位；建议在 Settings → Model Providers → Add Provider 中填写下方字段，不直接覆盖 ZCode 内部配置文件。',
    metadata: '完整模型目录', metadataHint: '目录只提供配置信息，不保证当前有服务。实际调用由网关返回结果或错误。',
    loading: '正在读取模型目录…', failed: '模型目录读取失败，可重试。通用 BaseURL 和 APIKey 仍可复制。',
    retry: '重新读取目录', copyCatalog: '复制完整目录 JSON', missing: '此客户端的完整模型配置需要目录数据，请先读取或重试。',
    invalid: 'BaseURL 无效，请检查站点 API 地址设置。', unsupported: '目录中有此客户端暂不支持的协议，请参考完整 JSON 和客户端说明。',
    protocol: '模型声明缺省协议时按 OpenAI Chat Completions 生成；不按服务状态筛选。原始元数据完整保留在目录 JSON 中。',
    modelHint: '此处仅配置 Provider，不改默认模型。模型选择沿用客户端自身操作；完整元数据可在下方查看。',
    openCatalog: '打开目录', emptyKey: '未提供 API Key'
  },
  en: {
    title: 'Use API Key', base: 'Copy BaseURL', key: 'Copy APIKey', both: 'Copy BaseURL + APIKey',
    clients: 'Client configuration', back: 'Back to credentials', copy: 'Copy configuration', docs: 'Official guide',
    intro: 'Merge snippets into your user-level configuration and retain existing settings. Snippets contain secrets; do not commit or share them.',
    defaultLocation: 'Default configuration location', copyPath: 'Copy default path', discouraged: 'Not recommended',
    locationHint: 'These are client defaults. ~ and %USERPROFILE% mean your own home directory. This site does not read local files or discover custom directories. If you changed the location, find it yourself. Create missing files or merge existing ones; do not overwrite the entire configuration.',
    discouragedHint: 'This site does not recommend this client. Default configuration is still provided for your own choice.',
    zcodeHint: 'The default file path is for reference. Enter the fields below in Settings → Model Providers → Add Provider instead of overwriting ZCode’s internal configuration.',
    metadata: 'Complete model catalog', metadataHint: 'This is configuration metadata, not a service-availability guarantee. Actual calls return gateway results or errors.',
    loading: 'Loading model catalog…', failed: 'Could not read the catalog. Retry to get the model declarations; BaseURL and APIKey can still be copied.',
    retry: 'Reload catalog', copyCatalog: 'Copy complete catalog JSON', missing: 'This client needs catalog data for its complete model configuration. Load or retry first.',
    invalid: 'Invalid BaseURL. Check the site API endpoint setting.', unsupported: 'The catalog contains a protocol this client does not support. Refer to the complete JSON and client guide.',
    protocol: 'An omitted model protocol defaults to OpenAI Chat Completions. Models are not filtered by availability. The catalog JSON retains all original metadata.',
    modelHint: 'These snippets configure the provider without changing the default model. Select models in your client; the complete metadata is available below.',
    openCatalog: 'Open catalog', emptyKey: 'No API key provided'
  }
}

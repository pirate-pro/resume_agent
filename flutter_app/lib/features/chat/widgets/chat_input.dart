import 'package:flutter/material.dart';
import 'package:agent_runtime/core/theme/app_theme.dart';
import 'package:agent_runtime/features/chat/widgets/skill_menu.dart';
import 'package:agent_runtime/shared/models/skill.dart';

class ChatInput extends StatefulWidget {
  final Function(String, List<String>) onSend;
  final bool isSending;
  final List<Skill> skills;
  final List<String> selectedSkills;
  final Function(List<String>) onSkillsChanged;

  const ChatInput({
    required this.onSend,
    required this.isSending,
    required this.skills,
    required this.selectedSkills,
    required this.onSkillsChanged,
  });

  @override
  _ChatInputState createState() => _ChatInputState();
}

class _ChatInputState extends State<ChatInput> {
  final _controller = TextEditingController();
  final _focusNode = FocusNode();
  bool _showUploadMenu = false;
  String? _selectedFile;
  bool _showSkillMenu = false;
  List<String> _tempSelectedSkills = [];

  @override
  void initState() {
    super.initState();
    _tempSelectedSkills = List.from(widget.selectedSkills);
  }

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppTokens.shellBg,
        border: Border(
          top: BorderSide(
            color: AppTokens.textSub.withOpacity(0.2),
            width: 1,
          ),
        ),
      ),
      padding: EdgeInsets.all(AppTokens.spacingMd),
      child: Column(
        children: [
          if (_selectedFile != null) ...[
            _buildSelectedFile(),
            SizedBox(height: AppTokens.spacingMd),
          ],
          if (_showSkillMenu) ...[
            SkillMenu(
              skills: widget.skills,
              selectedSkills: _tempSelectedSkills,
              onSelectionChanged: (skills) {
                setState(() {
                  _tempSelectedSkills = skills;
                });
              },
              onDismiss: () {
                setState(() {
                  _showSkillMenu = false;
                  widget.onSkillsChanged(_tempSelectedSkills);
                });
              },
            ),
            SizedBox(height: AppTokens.spacingMd),
          ],
          Row(
            children: [
              _buildUploadButton(),
              Expanded(
                child: _buildTextField(),
              ),
              _buildSendButton(),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildUploadButton() {
    return IconButton(
      icon: Icon(
        Icons.attach_file,
        color: AppTokens.textSub,
        size: 24,
      ),
      onPressed: () {
        setState(() {
          _showUploadMenu = !_showUploadMenu;
        });
      },
    );
  }

  Widget _buildTextField() {
    return TextField(
      controller: _controller,
      focusNode: _focusNode,
      decoration: InputDecoration(
        hintText: '输入消息后回车发送，Shift+Enter 换行；输入 / 选择技能',
        hintStyle: TextStyle(
          color: AppTokens.textSub,
          fontSize: AppTokens.fontSizeSm,
        ),
        border: InputBorder.none,
        contentPadding: EdgeInsets.zero,
      ),
      style: TextStyle(
        fontSize: AppTokens.fontSizeBase,
        color: AppTokens.textMain,
      ),
      maxLines: 5,
      minLines: 1,
      onChanged: (text) {
        if (text.endsWith('/') && text.trim().length > 1) {
          setState(() {
            _showSkillMenu = true;
          });
        }
      },
      onSubmitted: (text) {
        if (text.trim().isNotEmpty) {
          widget.onSend(text, _tempSelectedSkills);
          _controller.clear();
        }
      },
      onTap: () {
        if (_showUploadMenu) {
          setState(() {
            _showUploadMenu = false;
          });
        }
      },
    );
  }

  Widget _buildSendButton() {
    return IconButton(
      icon: Icon(
        widget.isSending ? Icons.stop : Icons.send,
        color: widget.isSending ? AppTokens.danger : AppTokens.accent,
        size: 24,
      ),
      onPressed: widget.isSending
          ? null
          : () {
              final text = _controller.text.trim();
              if (text.isNotEmpty) {
                widget.onSend(text, _tempSelectedSkills);
                _controller.clear();
              }
            },
    );
  }

  Widget _buildSelectedFile() {
    return Container(
      padding: EdgeInsets.all(AppTokens.spacingSm),
      decoration: BoxDecoration(
        color: AppTokens.hoverBg,
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
        border: Border.all(
          color: AppTokens.accent.withOpacity(0.3),
        ),
      ),
      child: Row(
        children: [
          Icon(
            Icons.file_present,
            color: AppTokens.accent,
            size: 20,
          ),
          SizedBox(width: AppTokens.spacingSm),
          Expanded(
            child: Text(
              _selectedFile!,
              style: TextStyle(
                fontSize: AppTokens.fontSizeSm,
                color: AppTokens.textMain,
              ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          IconButton(
            icon: Icon(
              Icons.close,
              color: AppTokens.textSub,
              size: 18,
            ),
            onPressed: () {
              setState(() {
                _selectedFile = null;
              });
            },
          ),
        ],
      ),
    );
  }
}

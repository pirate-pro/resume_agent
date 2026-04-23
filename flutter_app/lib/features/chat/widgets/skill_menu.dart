import 'package:flutter/material.dart';
import 'package:agent_runtime/core/theme/app_theme.dart';
import 'package:agent_runtime/shared/models/skill.dart';

class SkillMenu extends StatefulWidget {
  final List<Skill> skills;
  final List<String> selectedSkills;
  final Function(List<String>) onSelectionChanged;
  final VoidCallback onDismiss;

  const SkillMenu({
    required this.skills,
    required this.selectedSkills,
    required this.onSelectionChanged,
    required this.onDismiss,
  });

  @override
  _SkillMenuState createState() => _SkillMenuState();
}

class _SkillMenuState extends State<SkillMenu> {
  late List<Skill> _skills;
  late List<String> _selectedSkills;

  @override
  void initState() {
    super.initState();
    _skills = List.from(widget.skills);
    _selectedSkills = List.from(widget.selectedSkills);
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: EdgeInsets.only(top: 8),
      decoration: BoxDecoration(
        color: AppTokens.shellBg,
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
        border: Border.all(
          color: AppTokens.textSub.withOpacity(0.2),
        ),
        boxShadow: [AppTokens.shadowMd],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          _buildHeader(),
          Divider(
            color: AppTokens.textSub.withOpacity(0.2),
            height: 1,
          ),
          _buildSkillList(),
        ],
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      padding: EdgeInsets.all(AppTokens.spacingMd),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            '选择技能',
            style: TextStyle(
              fontSize: AppTokens.fontSizeSm,
              fontWeight: AppTokens.fontWeightMedium,
              color: AppTokens.textSub,
            ),
          ),
          TextButton(
            onPressed: () {
              widget.onDismiss();
            },
            child: Text(
              '完成',
              style: TextStyle(
                fontSize: AppTokens.fontSizeSm,
                color: AppTokens.accent,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSkillList() {
    return Container(
      constraints: BoxConstraints(
        maxHeight: 200,
      ),
      child: ListView.builder(
        shrinkWrap: true,
        itemCount: _skills.length,
        itemBuilder: (context, index) {
          final skill = _skills[index];
          final isSelected = _selectedSkills.contains(skill.id);

          return CheckboxListTile(
            title: Text(
              skill.name,
              style: TextStyle(
                fontSize: AppTokens.fontSizeSm,
                color: AppTokens.textMain,
              ),
            ),
            subtitle: Text(
              skill.description,
              style: TextStyle(
                fontSize: AppTokens.fontSizeXs,
                color: AppTokens.textSub,
              ),
            ),
            value: isSelected,
            onChanged: (selected) {
              setState(() {
                if (selected == true) {
                  _selectedSkills.add(skill.id);
                } else {
                  _selectedSkills.remove(skill.id);
                }
                widget.onSelectionChanged(_selectedSkills);
              });
            },
            controlAffinity: ListTileControlAffinity.leading,
            activeColor: AppTokens.accent,
            checkColor: AppTokens.shellBg,
          );
        },
      ),
    );
  }
}

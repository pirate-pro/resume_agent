import 'package:flutter/material.dart';
import 'package:agent_runtime/core/theme/app_theme.dart';

class MaxRoundsSetting extends StatefulWidget {
  final int maxRounds;
  final Function(int) onMaxRoundsChanged;

  const MaxRoundsSetting({
    required this.maxRounds,
    required this.onMaxRoundsChanged,
  });

  @override
  _MaxRoundsSettingState createState() => _MaxRoundsSettingState();
}

class _MaxRoundsSettingState extends State<MaxRoundsSetting> {
  late int _currentValue;

  @override
  void initState() {
    super.initState();
    _currentValue = widget.maxRounds;
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.all(AppTokens.spacingMd),
      decoration: BoxDecoration(
        color: AppTokens.shellBg,
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '最大工具轮次',
            style: TextStyle(
              fontSize: AppTokens.fontSizeSm,
              fontWeight: AppTokens.fontWeightMedium,
              color: AppTokens.textSub,
            ),
          ),
          SizedBox(height: AppTokens.spacingSm),
          Row(
            children: [
              Expanded(
                child: Slider(
                  value: _currentValue.toDouble(),
                  min: 0,
                  max: 10,
                  divisions: 10,
                  label: '$_currentValue',
                  activeColor: AppTokens.accent,
                  inactiveColor: AppTokens.textSub.withOpacity(0.3),
                  onChanged: (value) {
                    setState(() {
                      _currentValue = value.toInt();
                      widget.onMaxRoundsChanged(_currentValue);
                    });
                  },
                ),
              ),
              SizedBox(width: AppTokens.spacingMd),
              Container(
                padding: EdgeInsets.symmetric(
                  horizontal: AppTokens.spacingSm,
                  vertical: AppTokens.spacingSm - 2,
                ),
                decoration: BoxDecoration(
                  color: AppTokens.hoverBg,
                  borderRadius: BorderRadius.circular(AppTokens.radiusSm),
                ),
                child: Text(
                  '$_currentValue',
                  style: TextStyle(
                    fontSize: AppTokens.fontSizeSm,
                    fontWeight: AppTokens.fontWeightMedium,
                    color: AppTokens.accent,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}